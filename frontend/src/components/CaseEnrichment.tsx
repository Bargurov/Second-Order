import type { ReactNode } from "react";
import {
  ASPECTS, CHECK_STATES, type Aspect, type CheckState, type ClaimCheck, type Enrichment,
} from "../caseEnrichment";
import { Link } from "../router";

const ASPECT_LABELS: Record<Aspect, string> = {
  instrument: "Instrument", scope: "Scope", timing: "Timing", conditions: "Conditions",
};
const STATEMENT_LABELS = {
  stated: "Stated", not_stated: "Not stated", referenced_unread: "In a referenced document, not read",
} as const;
const CHECK_LABELS: Record<CheckState, string> = {
  consistent: "Consistent", qualified: "Consistent, with a qualifier", discrepancy: "Differs", not_found: "Not found",
};
const COPY_LABELS: Record<string, string> = {
  verified: "Verified on this machine", absent: "Not on this machine", different: "Differs from its record",
};

const External = ({ href, children }: { href: string; children: ReactNode }) => (
  <a className="library-external" href={href} target="_blank" rel="noreferrer">{children}</a>
);

/** Marks, where it appears, a claim of the case that its retained source contradicts. */
export function DiscrepancyFlag({ check }: { check: ClaimCheck | undefined }) {
  if (!check) return null;
  return (
    <a className="enrichment-flag" href="#check" data-target={check.target}>Differs from the retained source</a>
  );
}

const COUNT_WORDS: Record<CheckState, (count: number) => string> = {
  consistent: () => "consistent", qualified: () => "consistent with a qualifier",
  discrepancy: (count) => (count === 1 ? "differs" : "differ"), not_found: () => "not found",
};

function summaryLine(enrichment: Enrichment): string {
  const total = enrichment.claim_checks.length;
  const parts = CHECK_STATES.map((state) => `${enrichment.counts[state]} ${COUNT_WORDS[state](enrichment.counts[state])}`);
  return `${total} claims of this case were checked against the retained sources: ${parts.join(", ")}.`;
}

/** The source check and reading aid: one compact panel; the case's own text is never changed by it. */
export function EnrichmentPanel({ enrichment }: { enrichment: Enrichment }) {
  const roles = new Map(enrichment.sources.map((source) => [source.id, source.role]));
  const differing = enrichment.claim_checks.filter((check) => check.status === "discrepancy");
  const references = new Map(enrichment.references.map((reference) => [reference.id, reference]));
  return (
    <div className="enrichment-panel">
      {differing.length > 0 && (
        <div className="enrichment-discrepancies" role="note" aria-label="Differences from the retained sources">
          <p className="kicker">Differs from the retained source</p>
          <ul>
            {differing.map((check) => (
              <li key={check.target}>
                <strong>{check.label}.</strong> {check.note}{" "}
                <span className="enrichment-source">Source: {roles.get(check.source)}.</span>
              </li>
            ))}
          </ul>
          <p>The case text is left as written; each of these claims is marked where it appears.</p>
        </div>
      )}
      <p className="enrichment-summary">{summaryLine(enrichment)}</p>
      <p className="library-method">{enrichment.not_checked}</p>

      <div className="enrichment-chain library-reading-side">
        <p className="kicker enrichment-label">Where in the semiconductor chain · {enrichment.chain_label}</p>
        <p className="enrichment-chain-text">{enrichment.chain.placement}</p>
        <p className="enrichment-chain-basis">{enrichment.chain.basis}</p>
      </div>

      <table className="library-facts enrichment-readout">
        <thead><tr><th scope="col">Aspect</th><th scope="col">What the release states, and what it does not</th></tr></thead>
        <tbody>
          {ASPECTS.map((aspect) => (
            <tr key={aspect}>
              <th scope="row" data-label="Aspect">{ASPECT_LABELS[aspect]}</th>
              <td data-label="Statements">
                <ul>
                  {enrichment.readout.filter((item) => item.aspect === aspect).map((item) => (
                    <li key={item.text} data-status={item.status}>
                      <span className={`enrichment-status is-${item.status}`}>{STATEMENT_LABELS[item.status]}</span>
                      {item.text}
                      {item.reference && references.get(item.reference) && (
                        <> <span className="enrichment-source">(Listed under referenced documents.)</span></>
                      )}
                    </li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {enrichment.references.length > 0 && (
        <>
          <h3>Referenced documents, not read</h3>
          <ul className="library-points enrichment-references">
            {enrichment.references.map((reference) => (
              <li key={reference.id}>
                {reference.description}.
                {reference.url && <> <External href={reference.url}>Official address</External></>}
              </li>
            ))}
          </ul>
          <p className="library-method">These documents were not read; nothing in them is inferred here.</p>
        </>
      )}

      {enrichment.comparison && (
        <>
          <h3>Compared with a historical case</h3>
          <p className="enrichment-comparison">{enrichment.comparison.text}</p>
          <p className="enrichment-comparison-link">
            <Link to={enrichment.comparison.href}>{enrichment.comparison.title}</Link> (historical case, quoted from
            its own retained release)
          </p>
          <details className="enrichment-more">
            <summary>Facts cited from the historical case ({enrichment.comparison.facts.length})</summary>
            <ul className="library-points">
              {enrichment.comparison.facts.map((fact) => <li key={fact.id}>{fact.text}</li>)}
            </ul>
          </details>
        </>
      )}

      <details className="enrichment-more">
        <summary>Claims checked ({enrichment.claim_checks.length})</summary>
        <p className="library-method">
          Each claim is checked against the press release the case was written from, unless another source is named.
        </p>
        <table className="library-facts enrichment-checks">
          <thead><tr><th scope="col">Claim</th><th scope="col">Result</th><th scope="col">Note</th></tr></thead>
          <tbody>
            {enrichment.claim_checks.map((check) => (
              <tr key={check.target} data-status={check.status}>
                <th scope="row" data-label="Claim">{check.label}</th>
                <td data-label="Result"><span className={`enrichment-check is-${check.status}`}>
                  {CHECK_LABELS[check.status]}</span></td>
                <td data-label="Note">{check.note ?? "As the retained source states it."}
                  {check.source !== "release" && (
                    <> <span className="enrichment-source">Source: {roles.get(check.source)}.</span></>
                  )}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      <details className="enrichment-more">
        <summary>What would be needed to examine each channel</summary>
        {enrichment.examination.map((entry) => (
          <div key={entry.channel} className="enrichment-examination">
            <h4>{entry.channel}</h4>
            <ul className="library-points">{entry.observations.map((text) => <li key={text}>{text}</li>)}</ul>
          </div>
        ))}
        <p className="library-method">{enrichment.examination_note}</p>
      </details>

      <details className="enrichment-more">
        <summary>Sources, retained copies and provenance</summary>
        {enrichment.sources.map((source, index) => (
          <dl key={source.id} className="ledger enrichment-source-ledger">
            <div><dt>Source</dt><dd>{source.role}</dd></div>
            <div><dt>Title</dt><dd>{source.title}</dd></div>
            <div><dt>Publisher</dt><dd>{source.publisher}</dd></div>
            {source.date_as_stated && <div><dt>As stated</dt><dd>{source.date_as_stated}</dd></div>}
            <div><dt>Official source</dt><dd><External href={source.url}>{source.url}</External></dd></div>
            <div><dt>Retained copy</dt><dd>
              Kept privately, not served: {source.retained.bytes.toLocaleString("en-US")} bytes, SHA-256{" "}
              <code>{source.retained.sha256}</code>, approval {source.retained.approval_id}, received{" "}
              {source.retained.retrieved_at}; charset {source.retained.charset}
            </dd></div>
            <div><dt>Copy check</dt><dd>
              {COPY_LABELS[enrichment.copies[index].state]}. {enrichment.copies[index].detail}
            </dd></div>
          </dl>
        ))}
        <dl className="ledger enrichment-provenance">
          <div><dt>Prepared by</dt><dd>{enrichment.provenance.prepared_by}</dd></div>
          <div><dt>Prepared on</dt><dd>{enrichment.provenance.prepared_on}</dd></div>
          <div><dt>Human review</dt><dd>None: not reviewed by a person</dd></div>
          <div><dt>Research use</dt><dd>Excluded: never frozen, scored or counted</dd></div>
        </dl>
        <p className="library-method">{enrichment.provenance.method}</p>
      </details>
    </div>
  );
}
