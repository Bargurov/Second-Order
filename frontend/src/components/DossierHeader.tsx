import type { CSSProperties } from "react";
import { NOT_EVALUATED, VERDICT_LABEL, authorshipNote, formatUtc, shortHash, verdictMeaning } from "../format";
import type { Dossier } from "../types";

export function DossierHeader({ dossier }: { dossier: Dossier }) {
  const { hypothesis, evaluation, research } = dossier;
  const note = authorshipNote(hypothesis);
  const ledger: [string, string, string?][] = [
    ["Published", formatUtc(hypothesis.event.published_at)],
    ["Created / frozen (actual)", formatUtc(hypothesis.frozen_at)],
    ["Simulated replay as of", hypothesis.replay_as_of ? formatUtc(hypothesis.replay_as_of) : "— (prospective)"],
    ["Evaluated as of", evaluation ? formatUtc(evaluation.as_of) : NOT_EVALUATED],
    ["Engine", `${hypothesis.engine.provider} · ${hypothesis.engine.model}`],
    ["Prompt hash", shortHash(hypothesis.engine.prompt_hash, 12), hypothesis.engine.prompt_hash],
    ...(evaluation
      ? ([
          ["Schema · rules", `${hypothesis.engine.schema_version} · ${evaluation.rules.version}`],
          ["Rules hash", shortHash(evaluation.rules_hash, 12), evaluation.rules_hash],
          ["Data hash", shortHash(evaluation.data_hash, 12), evaluation.data_hash],
        ] as [string, string, string?][])
      : ([["Schema", hypothesis.engine.schema_version]] as [string, string][])),
    ["Hypothesis ID", shortHash(dossier.id, 12), dossier.id],
  ];

  return (
    <header className="dossier-header reveal" style={{ "--i": 0 } as CSSProperties}>
      <div className="stamp-row">
        <span className="stamp">{dossier.label}</span>
        {note && <span className="stamp-note">{note}</span>}
      </div>
      <div className="headline-row">
        <div>
          <h1>{hypothesis.event.headline}</h1>
          <p className="source">
            Source:{" "}
            <a href={hypothesis.event.source_url} target="_blank" rel="noreferrer noopener">
              {new URL(hypothesis.event.source_url).hostname}
            </a>
            <span aria-hidden="true"> ↗</span>
          </p>
        </div>
        {evaluation ? (
          <aside className={`verdict-card verdict-${evaluation.verdict}`} aria-label="Dossier verdict">
            <p className="kicker">Dossier verdict · follows the primary leg</p>
            <p className="verdict-word">{VERDICT_LABEL[evaluation.verdict]}</p>
            <p className="verdict-note">{verdictMeaning(evaluation.verdict, evaluation.rules.upper, evaluation.rules.lower)}</p>
            <p className="research-note">{research.reason}</p>
          </aside>
        ) : (
          <aside className="verdict-card state-unevaluated" aria-label="Dossier verdict">
            <p className="kicker">Dossier verdict</p>
            <p className="verdict-word">{NOT_EVALUATED}</p>
            <p className="verdict-note">
              Frozen {formatUtc(hypothesis.frozen_at)}. No outcome has been recorded, so no leg has a verdict.
            </p>
            <p className="research-note">{research.reason}</p>
          </aside>
        )}
      </div>
      <p className="summary">{hypothesis.summary}</p>
      <dl className="ledger">
        {ledger.map(([term, value, full]) => (
          <div key={term}>
            <dt>{term}</dt>
            <dd title={full}>{value}</dd>
          </div>
        ))}
      </dl>
    </header>
  );
}
