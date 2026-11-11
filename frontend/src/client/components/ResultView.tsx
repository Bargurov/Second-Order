import type { ReactNode } from "react";
import type { Analysis } from "../../contracts/user.ts";
import { useClient, zoneOf } from "../context";
import { locator, markedSource } from "../evidence.ts";
import { BASIS_LABEL, OUTCOME_LABEL } from "../present.ts";
import { inZone } from "../time.ts";

function Items({ items, empty }: { items: ReactNode[]; empty: string }) {
  return items.length === 0 ? <p className="client-sub">{empty}</p> : <ul>{items}</ul>;
}

/** A recorded result: the source's quoted words, the generated interpretation and what remains unknown, as three
 * visibly different surfaces, with the quoted passages marked in the source text. */
export function ResultView({ analysis }: { analysis: Analysis }) {
  const { account } = useClient();
  const result = analysis.result!;
  const content = result.analysis;
  const zone = zoneOf(account);
  return (
    <>
      <section className="card client-card client-outcome" aria-labelledby="outcome-title" data-outcome={result.outcome}>
        <h2 id="outcome-title" data-focus-target="result" tabIndex={-1}>{OUTCOME_LABEL[result.outcome]}</h2>
        <p>{result.note}</p>
        {result.outcome === "declined" && (
          result.explanation
            ? <blockquote className="client-explanation"><span className="client-label">The reply's own words, not an
                analysis</span>{result.explanation}</blockquote>
            : <p className="client-sub">The reply gave no explanation.</p>
        )}
        <p className="client-sub">Recorded {inZone(result.recorded_at, zone)}. {analysis.retrospective}</p>
      </section>

      {content && (
        <>
          <section className="client-surface client-evidence" aria-labelledby="evidence-title">
            <h2 id="evidence-title">What the source establishes</h2>
            <p className="client-label">The publisher's own words, located in the text you supplied</p>
            <ol className="client-statements">
              {content.established.map((item) => (
                <li key={item.number} id={`statement-${item.number}`} data-statement={item.number}>
                  <p className="client-basis-label">{item.number}. {BASIS_LABEL[item.basis]}</p>
                  <p className="client-statement">{item.statement}</p>
                  {item.quotes.map((quote, index) => (
                    <figure key={index} className="client-quote-figure">
                      <blockquote>{quote.source_passage}</blockquote>
                      <figcaption>{locator(quote)}</figcaption>
                    </figure>
                  ))}
                </li>
              ))}
            </ol>
          </section>

          <section className="client-surface client-interpretation" aria-labelledby="interpretation-title">
            <h2 id="interpretation-title">Interpretation</h2>
            <p className="client-label">Generated interpretation, not the publisher's words</p>
            {content.interpretation.kind === "no_additional_finding" &&
              <p className="client-chip">No additional finding beyond what the source states</p>}
            <p className="client-interpretation-text">{content.interpretation.text}</p>
            {content.interpretation.based_on.length > 0 && (
              <p className="client-sub">Relies on established statement{content.interpretation.based_on.length > 1 ? "s" : ""}{" "}
                {content.interpretation.based_on.map((number, index) => (
                  <span key={number}>{index ? ", " : ""}<a href={`#statement-${number}`}>{number}</a></span>
                ))}.</p>
            )}
          </section>

          <section className="client-surface client-unknowns" aria-labelledby="unknowns-title">
            <h2 id="unknowns-title">What remains unknown</h2>
            <h3>Assumptions</h3>
            <Items items={content.assumptions.map((text) => <li key={text}>{text}</li>)} empty="None stated." />
            <h3>Competing explanations</h3>
            <Items items={content.competing_explanations.map((item) => (
              <li key={item.explanation}>{item.explanation} <span className="client-sub">What would tell them apart:{" "}
                {item.would_distinguish}</span></li>
            ))} empty="None stated." />
            <h3>Missing information</h3>
            <Items items={content.missing_information.map((text) => <li key={text}>{text}</li>)} empty="None stated." />
            <h3>What would test it</h3>
            <Items items={content.tests.map((item) => (
              <li key={item.check}>{item.check} <span className="client-sub">Counts against it if:{" "}
                {item.counts_against_if}</span></li>
            ))} empty="None stated." />
            <h3>Earlier baseline</h3>
            <p>{analysis.baseline.note}</p>
          </section>
        </>
      )}

      <details className="card client-card client-marked" open={content !== null}>
        <summary>The source text{content ? ", with the quoted passages marked" : ""}</summary>
        <pre className="client-marked-text">
          {markedSource(analysis.source.text, content).map((segment, index) => segment.statements.length > 0
            ? <mark key={index} title={`Quoted in statement ${segment.statements.join(", ")}`}>{segment.text}</mark>
            : <span key={index}>{segment.text}</span>)}
        </pre>
      </details>
    </>
  );
}
