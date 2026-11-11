import type { ReactNode } from "react";
import { formatUtc } from "../format";
import {
  OBSERVABLE_LABEL, ORIGIN_LABEL, providerName,
  type BaselineSummary, type EffectiveHypothesis, type Freshness, type Origin, type Scoring,
} from "../lifecycle";
import { Link } from "../router";

/** A table that may be wider than a phone: it scrolls sideways inside its own area, never the page. The area is named
 * and can take the keyboard's focus, so its hidden columns can be reached and every value read and copied whole. */
export function TableArea({ label, children }: { label: string; children: ReactNode }) {
  return <div className="lifecycle-table-area" role="region" aria-label={label} tabIndex={0}>{children}</div>;
}

/** The exact hypothesis content, its event metadata and where it came from. Shared by the preview and the record. */
export function EffectiveContent({ hypothesis, origin, bindings }: {
  hypothesis: EffectiveHypothesis; origin: Origin; bindings?: Record<string, string>;
}) {
  const precision = origin.publication_precision;
  return (
    <div className="freeze-block freeze-content">
      <h4>Hypothesis</h4>
      <dl className="ledger freeze-ledger">
        <div><dt>Headline</dt><dd>{hypothesis.event.headline}</dd></div>
        <div><dt>Source</dt><dd><a href={hypothesis.event.source_url} target="_blank" rel="noreferrer">
          {hypothesis.event.source_url}</a></dd></div>
        <div><dt>Published (UTC)</dt><dd>{formatUtc(hypothesis.event.published_at)}</dd></div>
        <div><dt>As supplied</dt><dd>{origin.published_at_as_supplied ?? "Not recorded here"}
          {precision ? ` (${precision})` : ""}</dd></div>
        <div><dt>Story</dt><dd>{hypothesis.story_id}</dd></div>
        <div><dt>Class · usage</dt><dd>{hypothesis.evidence_class} · {hypothesis.usage}</dd></div>
        <div><dt>Engine</dt><dd>{hypothesis.engine.provider} · {hypothesis.engine.model}</dd></div>
        <div><dt>Engine prompt hash</dt><dd>{hypothesis.engine.prompt_hash}</dd></div>
      </dl>
      <OriginNote origin={origin} />
      <p className="freeze-summary">{hypothesis.summary}</p>
      <TableArea label="The hypothesis's legs">
        <table className="freeze-legs">
          <thead><tr><th scope="col">Leg</th><th scope="col">Observable</th><th scope="col">Direction</th>
            <th scope="col">Horizon</th><th scope="col">Link</th><th scope="col">Headline reports it</th></tr></thead>
          <tbody>{hypothesis.legs.map((leg) => (
            <tr key={leg.id} data-leg={leg.id}>
              <th scope="row">{leg.id}{leg.primary ? " (primary)" : ""}</th>
              <td>{OBSERVABLE_LABEL[leg.observable_id] ?? leg.observable_id}
                {bindings?.[leg.observable_id] ? <><br /><code>{bindings[leg.observable_id]}</code></> : null}</td>
              <td>{leg.expected}</td><td>{leg.horizon} obs.</td><td>{leg.link}</td>
              <td>{leg.headline_reports_move ? "yes" : "no"}</td>
            </tr>
          ))}</tbody>
        </table>
      </TableArea>
      <ul className="freeze-leg-text">{hypothesis.legs.map((leg) => (
        <li key={leg.id}><strong>{leg.id}</strong> — channel: {leg.channel}. Rationale: {leg.rationale} Falsifier:
          {" "}{leg.falsifier}</li>
      ))}</ul>
    </div>
  );
}

function OriginNote({ origin }: { origin: Origin }) {
  if (origin.kind === "manual") {
    return <p className="freeze-origin">{ORIGIN_LABEL.manual}: the submitted input's SHA-256 is
      {" "}<code>{origin.manual_input_sha256}</code>, kept with the freeze record.</p>;
  }
  if (origin.kind === "model") {
    const corrected = origin.corrections
      ? (origin.corrections.summary !== null ? 1 : 0) + Object.values(origin.corrections.legs)
        .reduce((sum, fields) => sum + Object.keys(fields).length, 0) : 0;
    return (
      <p className="freeze-origin">{ORIGIN_LABEL.model}: <Link to={`/?draft=${origin.draft_id}`}>draft
        {" "}{origin.draft_id?.slice(0, 12)}</Link> from {origin.model} under {origin.prompt_version}; review version
        {" "}{origin.review?.sequence} ({origin.review?.status?.replace("_", " ")}, saved {origin.review?.saved_at
          ? formatUtc(origin.review.saved_at) : "?"}) against view <code>{origin.draft_view_sha256?.slice(0, 12)}</code>;
        {" "}{corrected} reviewed correction{corrected === 1 ? "" : "s"} applied. The model's own output
        (<code>{origin.model_output_sha256?.slice(0, 12)}</code>) and its records are unchanged.</p>
    );
  }
  return <p className="freeze-origin">{ORIGIN_LABEL.outside_interface}. {origin.note}</p>;
}

/** The baseline's provider, possession time, vintage (none for H.15) and coverage. */
export function BaselineCard({ baseline }: { baseline: BaselineSummary | null }) {
  if (!baseline) return null;
  return (
    <div className="freeze-block freeze-baseline-card">
      <h4>Baseline</h4>
      <dl className="ledger freeze-ledger">
        <div><dt>Snapshot</dt><dd>{baseline.snapshot_id}</dd></div>
        <div><dt>Provider</dt><dd>{providerName(baseline.provider)}</dd></div>
        <div><dt>Held since</dt><dd>{formatUtc(baseline.retrieved_at)}</dd></div>
        <div><dt>Vintage</dt><dd>{baseline.vintage_date === null ? "None: no historical vintage" : baseline.vintage_date}</dd></div>
        {baseline.package && <div><dt>Package</dt><dd>{baseline.package.package_id}</dd></div>}
        {baseline.source_prepared_as_stated && (
          <div><dt>Source prepared (as stated)</dt><dd>{baseline.source_prepared_as_stated} (no time zone; not used)</dd></div>
        )}
      </dl>
      <p className="freeze-note">{baseline.possession_note}</p>
      <ul>{Object.entries(baseline.coverage).map(([series, entry]) => (
        <li key={series}><code>{series}</code>: classified {entry.classified_from} to {entry.classified_through}
          {entry.rows !== undefined ? `, ${entry.rows} dated rows` : ""}</li>
      ))}</ul>
    </div>
  );
}

export function FreshnessList({ freshness, note }: { freshness: Freshness | null; note?: string }) {
  if (!freshness) return null;
  return (
    <div className="freeze-block freeze-freshness">
      <h4>Freshness ({freshness.policy})</h4>
      {note && <p className="freeze-note">{note}</p>}
      {freshness.problem ? <p className="freeze-problem">{freshness.problem}</p> : (
        <ul>
          <li>Last expected session before the publication date {freshness.published_date}: {freshness.required_session}</li>
          {Object.entries(freshness.series ?? {}).map(([series, entry]) => (
            <li key={series}><code>{series}</code>: covered (classified to {entry.classified_through}); that session is
              {" "}{entry.required_session_status.replace(/_/g, " ")}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ScoringNote({ scoring, convention }: { scoring: Scoring; convention: string }) {
  return (
    <div className="freeze-block freeze-scoring">
      <h4>Scoring window</h4>
      <p>{scoring.rule}</p>
      <p>New York freeze date {scoring.freeze_date_new_york}; expected scoring anchor {scoring.expected_score_anchor ?? "unknown"}.
        {" "}{Object.entries(scoring.legs).map(([leg, entry]) =>
          `${leg}: ${entry.horizon} observation${entry.horizon === 1 ? "" : "s"}, expected end ${entry.expected_target ?? "unknown"}`)
          .join("; ")}.</p>
      <p className="freeze-note">{scoring.note} {convention}</p>
    </div>
  );
}
