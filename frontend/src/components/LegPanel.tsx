import {
  ANCHOR_POLICY,
  formatChange,
  formatNumber,
  percent,
  unitDigits,
  verdictMeaning,
  verdictStatus,
} from "../format";
import type { JoinedLeg, Rules } from "../types";

interface Props {
  leg: JoinedLeg;
  /** The recorded rules; null before evaluation, when no rule has been applied. */
  rules: Rules | null;
}

export function LegPanel({ leg, rules }: Props) {
  const { definition, result, view, node } = leg;
  const status = verdictStatus(result?.verdict ?? null);
  const scored =
    !!result && result.measured_change !== null && result.signed_move !== null && result.percentile_rank !== null;
  const against = scored && (result?.signed_move ?? 0) < 0;
  const placebo = result?.placebo;

  return (
    <section className={`leg-panel ${status.className}`} aria-labelledby="leg-title">
      <p className="kicker">
        Selected leg · {definition.primary ? "primary" : "secondary"} · {definition.link}
      </p>
      <div className="leg-heading">
        <h3 id="leg-title">{node.label}</h3>
        <span className={`verdict-chip ${status.className}`}>{status.label}</span>
      </div>
      <p className="leg-ids">
        <code>{definition.observable_id}</code> · channel <code>{definition.channel}</code>
      </p>

      <dl className="figures">
        <div>
          <dt>Expected</dt>
          <dd>{definition.expected === "up" ? "↑ Up" : "↓ Down"}</dd>
        </div>
        <div>
          <dt>Scored horizon</dt>
          <dd>{definition.horizon} {definition.horizon === 1 ? "session" : "sessions"}</dd>
        </div>
        <div>
          <dt>Measured change</dt>
          <dd>{scored ? formatChange(result?.measured_change ?? 0, view.unit) : "—"}</dd>
        </div>
        <div>
          <dt>Signed move</dt>
          <dd>
            {scored ? formatNumber(result?.signed_move ?? 0, unitDigits(view.unit)) : "—"}
            {scored && <small>{against ? " against expectation" : " with expectation"}</small>}
          </dd>
        </div>
        <div>
          <dt>Percentile rank</dt>
          <dd>
            {scored ? (result?.percentile_rank ?? 0).toFixed(3) : "—"}
            {result && <small> of {result.reference_windows} windows</small>}
          </dd>
        </div>
        <div>
          <dt>Unit</dt>
          <dd>{view.unit}</dd>
        </div>
      </dl>

      <p className="verdict-line">
        <strong>{status.label}.</strong>{" "}
        {!result
          ? "Nothing has been measured or ranked; a result appears only with an explicit, stored evaluation."
          : scored && rules
            ? verdictMeaning(result.verdict, rules.upper, rules.lower)
            : result.reason}
      </p>
      {rules ? (
        <p className="rule">
          Rule {rules.version}: supported needs a positive signed move and rank ≥ {rules.upper.toFixed(2)};
          contradicted needs a negative signed move and rank ≤ {rules.lower.toFixed(2)}.
        </p>
      ) : (
        <p className="rule">The scoring rules are recorded with the evaluation; none has been applied yet.</p>
      )}

      <dl className="notes">
        <div>
          <dt>Rationale</dt>
          <dd>{definition.rationale}</dd>
        </div>
        <div>
          <dt>Falsifier</dt>
          <dd>{definition.falsifier} <small>(explanatory text; not adjudicated automatically)</small></dd>
        </div>
        <div>
          <dt>Anchor policy</dt>
          <dd>
            {!result
              ? "Recorded at evaluation."
              : result.anchor_policy
                ? ANCHOR_POLICY[result.anchor_policy] ?? result.anchor_policy
                : "—"}
          </dd>
        </div>
        <div>
          <dt>Headline reports this move</dt>
          <dd>{definition.headline_reports_move ? "Yes, so the leg is excluded when anchors coincide" : "No"}</dd>
        </div>
        {placebo && (
          <div>
            <dt>Placebo controls</dt>
            <dd>
              Same rule on {placebo.eligible} of {placebo.requested} control dates from the prior year: supported{" "}
              {percent(placebo.rates.supported)}, contradicted {percent(placebo.rates.contradicted)}, inconclusive{" "}
              {percent(placebo.rates.inconclusive)}. A measured baseline, not a significance test.
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
}
