/**
 * Representative Live Case — one restrained editorial band on Evidence
 * Overview that explains why the published USTR tariff case is worth opening
 * and links to its full saved analysis.
 *
 * Product framing, not a research conclusion: the band orients a reviewer
 * (why this case, what to inspect, what the limits are, where the full
 * analysis lives) and never reproduces the analysis itself.  The case
 * resolves from its immutable candidate identity through the provider-free
 * orientation read; a missing or unlinked identity renders one explicit
 * unavailable line — never a substitute case, never a hidden section.
 *
 * Split per project test convention: `RepresentativeLiveCaseView` is pure
 * (renderToStaticMarkup-testable); `RepresentativeLiveCase` is the thin
 * query wrapper.
 */
import { useQuery } from "@tanstack/react-query";
import { api, type RepresentativeCase } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { qualityTierLabel } from "@/lib/analysis-readout";
import {
  provenanceLabel,
  type ProvenanceStatus,
  PROVENANCE_STATES,
} from "@/lib/analysis-provenance";

/** The one curated case this band presents.  Immutable candidate identity
 *  of the A3-published USTR Section 338 analysis; the linked event id is
 *  resolved at read time, never hardcoded here. */
export const REPRESENTATIVE_LIVE_CASE_CANDIDATE_ID = "aei-13530-f0a9907a";

/** Curated rationale — product framing only, no new research claim. */
export const REPRESENTATIVE_CASE_RATIONALE =
  "A named policy instrument from an official source, traced through " +
  "transmission steps, affected assets, counterforces, proof requirements, " +
  "and explicit evidence limits.";

/** Reviewer cues — what to inspect inside the full analysis. */
export const REPRESENTATIVE_CASE_CUES: ReadonlyArray<{
  label: string;
  detail: string;
}> = [
  {
    label: "Transmission",
    detail: "How the tariff mechanism moves through actors, channels and timing.",
  },
  {
    label: "Resolution",
    detail: "What evidence would strengthen, weaken or falsify the thesis.",
  },
  {
    label: "Provenance",
    detail: "Which source and analysis basis produced the saved readout.",
  },
];

/** Visible limits — claim ceilings this band must never soften. */
export const REPRESENTATIVE_CASE_LIMITS =
  "Single-source evidence · model-generated structured hypothesis · " +
  "descriptive, not causal · not a recommendation.";

export const UNAVAILABLE_COPY: Record<string, string> = {
  CASE_UNLINKED:
    "The representative case is not linked to a saved analysis yet.",
  CASE_NOT_FOUND:
    "The representative case identity was not found in the current registry.",
  SAVED_ANALYSIS_UNAVAILABLE:
    "The saved analysis for the representative case is unavailable.",
  PROVENANCE_UNAVAILABLE:
    "The representative case is saved without a captured analysis basis.",
  INVALID: "The representative case identity did not resolve.",
  ERROR: "The representative case could not be read.",
};

function basisLabel(status: string | null | undefined): string | null {
  if (!status) return null;
  return (PROVENANCE_STATES as readonly string[]).includes(status)
    ? provenanceLabel(status as ProvenanceStatus)
    : status;
}

/** Pure: the arguments the CTA hands to the saved-analysis launch, or null
 *  when the case cannot honestly be opened. */
export function launchArgsFor(
  c: RepresentativeCase | null | undefined,
): { headline: string; eventId: number } | null {
  if (!c || c.availability !== "AVAILABLE") return null;
  if (typeof c.analysis_event_id !== "number" || !c.headline) return null;
  return { headline: c.headline, eventId: c.analysis_event_id };
}

export type RepresentativeCaseViewState =
  | { kind: "pending" }
  | { kind: "unavailable"; reason: string }
  | { kind: "available"; data: RepresentativeCase };

/** Pure: fold the query outcome into one view state. */
export function viewStateFor(
  data: RepresentativeCase | undefined,
  isError: boolean,
  isPending: boolean,
): RepresentativeCaseViewState {
  if (isPending) return { kind: "pending" };
  if (isError || !data) return { kind: "unavailable", reason: "ERROR" };
  if (data.availability !== "AVAILABLE") {
    return { kind: "unavailable", reason: data.availability };
  }
  return { kind: "available", data };
}

export function RepresentativeLiveCaseView({
  state,
  onOpenAnalysis,
}: {
  state: RepresentativeCaseViewState;
  /** Navigates to the normal saved-analysis experience (numeric reopen). */
  onOpenAnalysis?: (headline: string, opts: { eventId: number }) => void;
}) {
  if (state.kind === "pending") {
    return (
      <Band>
        <p className="text-[12px] text-on-surface-variant/60">
          Loading the representative case…
        </p>
      </Band>
    );
  }

  if (state.kind === "unavailable") {
    return (
      <Band>
        <p className="text-[12px] leading-relaxed text-on-surface-variant/70">
          {UNAVAILABLE_COPY[state.reason] ?? UNAVAILABLE_COPY.ERROR}{" "}
          Nothing is substituted; the case renders only from its saved record.
        </p>
      </Band>
    );
  }

  const c = state.data;
  const tier = qualityTierLabel(c.quality_tier);
  const basis = basisLabel(c.basis_status);
  const launch = launchArgsFor(c);

  return (
    <Band>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">
          Official source · published analysis
        </span>
        {c.occurrence_date ? (
          <span className="font-mono text-[10px] tabular-nums text-on-surface-variant/55">
            occurred {c.occurrence_date}
          </span>
        ) : (
          <span className="font-mono text-[10px] text-on-surface-variant/45">
            occurrence date unavailable
          </span>
        )}
      </div>

      <h3 className="mt-1.5 max-w-[62ch] font-headline text-[15px] font-semibold leading-snug text-on-surface">
        {c.headline}
      </h3>

      <p className="mt-2 max-w-[70ch] text-[12px] leading-relaxed text-on-surface-variant/75">
        {REPRESENTATIVE_CASE_RATIONALE}
      </p>

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5 font-mono text-[10px] text-on-surface-variant/60">
        {(c.sources ?? []).map((s) => (
          <span key={s}>source: {s}</span>
        ))}
        {tier && <span>specification: {tier}</span>}
        {basis && <span>basis: {basis}</span>}
      </div>

      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-3">
        {REPRESENTATIVE_CASE_CUES.map((cue) => (
          <div key={cue.label} className="min-w-0">
            <dt className="text-[10px] uppercase tracking-[0.12em] text-on-surface-variant/55">
              {cue.label}
            </dt>
            <dd className="mt-0.5 text-[11px] leading-relaxed text-on-surface-variant/75">
              {cue.detail}
            </dd>
          </div>
        ))}
      </dl>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-t border-[color:var(--so-rule)] pt-2.5">
        <p className="text-[10px] leading-relaxed text-on-surface-variant/55">
          Representative case, not proof. {REPRESENTATIVE_CASE_LIMITS}
        </p>
        {launch && onOpenAnalysis && (
          <button
            type="button"
            onClick={() =>
              onOpenAnalysis(launch.headline, { eventId: launch.eventId })
            }
            className="shrink-0 rounded-sm border border-primary/35 px-3 py-1 text-[11px] font-medium text-primary transition-colors hover:bg-primary/10"
          >
            Open full analysis
          </button>
        )}
      </div>
    </Band>
  );
}

export function RepresentativeLiveCase({
  onOpenAnalysis,
}: {
  onOpenAnalysis?: (headline: string, opts: { eventId: number }) => void;
}) {
  const { data, isError, isPending } = useQuery({
    queryKey: qk.representativeCase(REPRESENTATIVE_LIVE_CASE_CANDIDATE_ID),
    queryFn: () =>
      api.representativeCase(REPRESENTATIVE_LIVE_CASE_CANDIDATE_ID),
    staleTime: 600_000,
  });
  return (
    <RepresentativeLiveCaseView
      state={viewStateFor(data, isError, isPending)}
      onOpenAnalysis={onOpenAnalysis}
    />
  );
}

function Band({ children }: { children: React.ReactNode }) {
  return (
    <section
      aria-label="Representative live case"
      className="rounded-md border border-[color:var(--so-rule-hi)] bg-surface-container-low/60 px-5 py-4"
    >
      <span className="text-[10px] uppercase tracking-[0.14em] text-on-surface-variant/50">
        Representative live case
      </span>
      <div className="mt-1">{children}</div>
    </section>
  );
}
