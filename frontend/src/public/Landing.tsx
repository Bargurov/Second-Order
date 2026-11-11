// The landing page a signed-out visitor sees at `/`: what Second Order does with a source you supply, how one analysis
// runs from the source to your own review, a worked example that is SYNTHETIC and says so, and credits in outline. It
// reads nothing from the server and states no number of credits: the credits page shows the server's own terms.
import { useEffect } from "react";
import { PUBLIC_PATHS } from "../contracts/onboarding.ts";
import type { SignedOutReason } from "../contracts/user.ts";
import { Link } from "../router";
import { EXAMPLE, EXAMPLE_LABEL } from "./example.ts";

const REASON: Record<SignedOutReason, string | null> = {
  not_signed_in: null,
  session_expired: "Your session has ended.",
  signed_out: "You are signed out.",
};

const STEPS: { title: string; text: string; free: boolean }[] = [
  { title: "Add a source", free: true,
    text: "Paste the text of a release, statement or report, with its headline, address and publication time." },
  { title: "Choose an Effort and prepare", free: true,
    text: "Choose one of the Effort levels this server offers. Preparing fixes exactly what would be analysed." },
  { title: "Ask for a quote", free: true,
    text: "The server states the exact credits for that prepared analysis, and until when the quote holds." },
  { title: "Approve, and it runs once", free: false,
    text: "Nothing runs until you approve the quote. Approving reserves its credits and one run of your daily " +
      "allowance; you are never charged more than the quote." },
  { title: "Read the result", free: true,
    text: "What the source establishes, each statement quoted from its text; a labelled interpretation; and what " +
      "remains unknown, kept apart." },
  { title: "Review and export", free: true,
    text: "Record your own judgment of the result, keep each version, and download the record." },
];

export function Landing({ reason }: { reason: SignedOutReason }) {
  useEffect(() => { document.title = "Second Order · Evidence-first research on the sources you supply"; }, []);
  return (
    <div className="public-landing" data-public="landing">
      {REASON[reason] && (
        <p className="public-reason" data-public="reason" role="status">{REASON[reason]}{" "}
          <Link to={PUBLIC_PATHS.signIn}>Sign in</Link> to continue.</p>
      )}
      <header className="public-hero">
        <p className="kicker">Second Order · Research workspace</p>
        <h1 tabIndex={-1}>Read a source for what it establishes, and for what it leaves open</h1>
        <p className="public-lede">Second Order reads an official release, statement or report that you supply,
          evidence first. It separates what the source states, quoted and located in its own text, from a labelled
          interpretation, the assumptions behind it, competing explanations and what is still unknown.</p>
        <p className="public-actions">
          <Link className="button" to={PUBLIC_PATHS.register}>Register</Link>
          <Link className="button button-quiet" to={PUBLIC_PATHS.signIn}>Sign in</Link>
        </p>
        <p className="public-small">An administrator approves every account, then allocates its credits and daily
          allowance. Until then, signing in shows your registration's status.</p>
      </header>

      <section className="public-section" aria-labelledby="how-title">
        <h2 id="how-title">How an analysis runs</h2>
        <ol className="public-steps">
          {STEPS.map((step) => (
            <li key={step.title}>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
              <p className={step.free ? "public-free" : "public-uses"}>
                {step.free ? "Uses no credits" : "Uses the quoted credits"}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="public-section public-example" aria-labelledby="example-title" data-public="example">
        <h2 id="example-title">What a result looks like</h2>
        <p className="public-synthetic">{EXAMPLE_LABEL}</p>
        <figure className="public-source">
          <figcaption><span className="public-source-publisher">{EXAMPLE.publisher}</span>
            <span className="public-source-headline">{EXAMPLE.headline}</span></figcaption>
          <p>{EXAMPLE.text}</p>
        </figure>
        <div className="public-surfaces">
          <section className="public-surface is-evidence" data-surface="evidence" aria-labelledby="example-evidence">
            <h3 id="example-evidence">What the source establishes</h3>
            <ol className="public-statements">
              {EXAMPLE.established.map((item) => (
                <li key={item.statement}>
                  <p className="public-basis">{item.basis}</p>
                  <p>{item.statement}</p>
                  <blockquote>{item.quote}</blockquote>
                </li>
              ))}
            </ol>
          </section>
          <section className="public-surface is-interpretation" data-surface="interpretation"
                   aria-labelledby="example-interpretation">
            <h3 id="example-interpretation">Interpretation</h3>
            <p className="public-basis">Generated interpretation, not the publisher's words</p>
            <p>{EXAMPLE.interpretation}</p>
            <p className="public-small">{EXAMPLE.basedOn}</p>
          </section>
          <section className="public-surface is-unknowns" data-surface="unknowns" aria-labelledby="example-unknowns">
            <h3 id="example-unknowns">What remains unknown</h3>
            <h4>Assumptions</h4>
            <ul>{EXAMPLE.assumptions.map((line) => <li key={line}>{line}</li>)}</ul>
            <h4>Competing explanations</h4>
            <ul>{EXAMPLE.competing.map((item) => (
              <li key={item.explanation}>{item.explanation} <span className="public-small">Would distinguish:
                {" "}{item.distinguish}</span></li>
            ))}</ul>
            <h4>Missing information</h4>
            <ul>{EXAMPLE.missing.map((line) => <li key={line}>{line}</li>)}</ul>
            <h4>What would test it</h4>
            <ul>{EXAMPLE.tests.map((item) => (
              <li key={item.check}>{item.check} <span className="public-small">Counts against it if: {item.against}</span></li>
            ))}</ul>
          </section>
        </div>
      </section>

      <section className="public-section public-two" aria-labelledby="credits-title">
        <div>
          <h2 id="credits-title">Credits</h2>
          <ul className="public-points">
            <li>A credit is a point of usage on this server. It has no money value and is not bought or sold here.</li>
            <li>The administrator allocates credits and a daily allowance of runs, as two separate steps.</li>
            <li>Every analysis gets its own quote before anything runs. Reading, reviewing and exporting use none.</li>
          </ul>
          <p><Link to={PUBLIC_PATHS.credits}>How credits work</Link>: the server's own rules and the quotes it would
            give now for three synthetic sources.</p>
        </div>
        <div>
          <h2 id="limits-title">What it is not</h2>
          <ul className="public-points">
            <li>Not a forecast and not trading advice: it is retrospective research on the text you supply.</li>
            <li>It reads only that text. It does not fetch, verify or add other sources.</li>
            <li>The interpretation is generated and labelled as such. Check it against the quoted evidence; your own
              review is part of the record.</li>
          </ul>
        </div>
      </section>
    </div>
  );
}
