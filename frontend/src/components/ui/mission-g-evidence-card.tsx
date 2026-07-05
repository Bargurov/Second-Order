/**
 * H3 — Mission G historical-evidence card.
 *
 * First in-product consumer of the completed Mission G research record
 * (`GET /evidence/mission-g`, the H2 contract).  Every computed research
 * number rendered here comes from the endpoint payload — the backend
 * parses the tracked `stats/G*.md` artifacts at request time, so this
 * card carries no hand-copied research figure.
 *
 * Information hierarchy (fixed by the research record, not by styling):
 *   1. evidence architecture — accepted lane vs historical lane, separate
 *      denominators, pooling prohibition;
 *   2. the dominant result — broad null + uniform instability counts;
 *   3. the single bounded exception, visually subordinate, with its
 *      calendar-time confound attached;
 *   4. failed / incomplete evidence — era-bounded secondary credit and
 *      the mechanism-comparability failure;
 *   5. representative cases as illustrations, never proof.
 *
 * Loading and unavailable states are honest: no value is invented.
 */
import type { MissionGEvidenceSummary } from "@/lib/api";

export interface MissionGEvidenceCardProps {
  /** Endpoint payload; `null` / `undefined` renders the loading state. */
  data?: MissionGEvidenceSummary | null;
  /** Explicit degraded state when the contract could not be loaded. */
  unavailable?: boolean;
}

function Band({
  kicker,
  children,
}: {
  kicker: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-on-surface-variant/55">
        {kicker}
      </p>
      {children}
    </div>
  );
}

function Provenance({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[10px] text-on-surface-variant/50">{children}</p>
  );
}

export function MissionGEvidenceCard({
  data,
  unavailable = false,
}: MissionGEvidenceCardProps) {
  if (unavailable) {
    return (
      <div className="flex flex-col gap-1 text-[12.5px] leading-relaxed text-on-surface-variant/85">
        <p>
          Mission G record unavailable: the <code>/evidence/mission-g</code>{" "}
          contract could not be loaded. No figures are shown in its place.
        </p>
      </div>
    );
  }
  if (!data) {
    return (
      <p className="text-[12.5px] leading-relaxed text-on-surface-variant/70">
        Loading the Mission G historical record&hellip;
      </p>
    );
  }

  const lanes = data.lanes;
  const hist = lanes.historical;
  const stability = data.stability;
  const opec = data.bounded_opec_association;
  const credit = data.credit_limitation;
  const g3b = data.failed_thesis_mechanism_comparability;
  const cases = data.representative_cases;
  const cov = g3b.classification_coverage_percent;

  return (
    <div className="flex flex-col gap-4 text-[12.5px] leading-relaxed text-on-surface/85">
      {/* 1 — evidence architecture: two lanes, hairline-separated, never pooled */}
      <div className="grid grid-cols-1 gap-px overflow-hidden rounded-md bg-white/[0.06] sm:grid-cols-2">
        <div className="flex flex-col gap-1 bg-surface-container-low p-3">
          <Band kicker="Accepted track record">
            <p className="font-mono text-[20px] tabular-nums leading-none text-on-surface">
              {lanes.accepted_track_record.count}
            </p>
            <p className="text-[11.5px] text-on-surface-variant/75">
              {lanes.accepted_track_record.lane_note}
            </p>
          </Band>
        </div>
        <div className="flex flex-col gap-1 bg-surface-container-low p-3">
          <Band kicker="Historical evidence — Mission G">
            <p className="font-mono text-[20px] tabular-nums leading-none text-on-surface">
              {hist.total}
            </p>
            <p className="font-mono text-[11px] tabular-nums text-on-surface-variant/85">
              {hist.fomc_frame_complete} FOMC frame-complete &middot;{" "}
              {hist.opec_designed_contrast} OPEC designed-contrast
            </p>
            <p className="text-[11.5px] text-on-surface-variant/75">
              {hist.lane_note}
            </p>
          </Band>
        </div>
      </div>
      <p className="text-[11.5px] italic text-on-surface-variant/70">
        {lanes.pooling_prohibition}
      </p>

      {/* 2 — dominant result: broad null + uniform instability, plain text */}
      <div className="flex flex-col gap-1.5 border-l-2 border-border/60 pl-3">
        <Band kicker="Main historical result">
          <p className="text-on-surface">{data.main_result.headline}</p>
          <p>{data.main_result.fomc_null.statement}</p>
          <p className="font-mono text-[12px] tabular-nums text-on-surface">
            Sign reversals under uniform stress:{" "}
            {stability.loeo_sign_reversals}/{stability.continuous_associations}{" "}
            leave-one-event-out &middot; {stability.loyo_sign_reversals}/
            {stability.continuous_associations} leave-one-calendar-year-out
          </p>
          <p className="text-[11.5px] text-on-surface-variant/75">
            {stability.note}
          </p>
        </Band>
      </div>

      {/* 3 — the single bounded exception, subordinate, confound attached */}
      <div className="flex flex-col gap-1 rounded-md border border-border/40 bg-surface-container p-3">
        <Band kicker="One bounded exception">
          <p className="text-[12px]">
            {opec.axis} ({opec.lane.replace(/_/g, " ")}):{" "}
            <span className="text-on-surface">{opec.wording}</span>.
          </p>
          <p className="font-mono text-[11px] tabular-nums text-on-surface-variant/85">
            {opec.per_horizon
              .map((h) => `${h.horizon}d rho ${h.rho.toFixed(4)}`)
              .join(" · ")}{" "}
            &middot; zero leave-one-out sign reversals at every horizon
          </p>
          <p className="text-[11.5px] text-on-surface-variant/75">
            Limitation: {opec.confound_note}.
          </p>
          <Provenance>
            wording &middot; verbatim from /evidence/mission-g (
            {data.source_artifacts.cases})
          </Provenance>
        </Band>
      </div>

      {/* 4 — failed and incomplete evidence, visible as results */}
      <div className="flex flex-col gap-2">
        <Band kicker="Failed and incomplete evidence">
          <p>
            <span className="font-mono tabular-nums text-on-surface">
              HY OAS {credit.available}/{credit.of}
            </span>{" "}
            &mdash; era-bounded coverage ({credit.fomc_subset} FOMC /{" "}
            {credit.opec_subset} OPEC), {credit.status} lens only;{" "}
            <span className="font-mono tabular-nums">
              {credit.fragile_associations}/{credit.of_associations}
            </span>{" "}
            of its associations flip sign under leave-one-out. {credit.note}.
          </p>
          <p>
            {g3b.statement}{" "}
            <span className="font-mono text-[11px] tabular-nums text-on-surface-variant/85">
              (classification coverage: {cov.accepted_news_headlines}% news
              headlines &middot; {cov.fomc_official_text}% FOMC official text
              &middot; {cov.opec_official_text}% OPEC official text)
            </span>
          </p>
        </Band>
      </div>

      {/* 5 — representative cases: identities only, illustrations */}
      <div className="flex flex-col gap-1 border-t border-border/30 pt-2.5">
        <Band kicker="Representative cases">
          <p className="text-[11.5px] text-on-surface-variant/75">
            {cases.unique_cases} state-anchored cases &mdash;{" "}
            <span className="text-on-surface">{cases.status}</span>.{" "}
            {cases.selection_note}.
          </p>
          <ul className="flex flex-col gap-0.5 font-mono text-[11px] text-on-surface-variant/85">
            {cases.cases.map((c) => (
              <li key={`${c.role}-${c.quantile}`} className="truncate">
                {c.role}/{c.quantile.toUpperCase()} &middot; {c.candidate_id}
              </li>
            ))}
          </ul>
        </Band>
      </div>

      {/* Non-claims, verbatim from the contract */}
      <div className="flex flex-col gap-0.5 text-[11px] text-on-surface-variant/65">
        {data.non_claims.map((line) => (
          <p key={line}>{line}</p>
        ))}
      </div>
    </div>
  );
}
