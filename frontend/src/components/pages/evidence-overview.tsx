/**
 * Evidence Overview (T5A) — a calm, app-native summary of the T2/T3/T4 baseline
 * research: the corpus snapshot, the marginal-preserving baseline (T2A), the
 * degenerate primary-only AR-sign (T2B), the multi-ticker AR result (T3A), and
 * the exposed-name coverage limitation (T4A).  Descriptive archive evidence —
 * not a trading or prediction surface; it adds no new analytics and no claims.
 *
 * Pure / presentational: it renders the static `RESEARCH_FINDINGS` snapshot.
 */
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";

import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { MissionGEvidenceCard } from "@/components/ui/mission-g-evidence-card";
import { MissionIEvidenceCard } from "@/components/ui/mission-i-evidence-card";
import { MissionJEvidenceCard } from "@/components/ui/mission-j-evidence-card";
import { UniversalEventDossiersCard } from "@/components/ui/universal-event-dossiers";
import { RepresentativeLiveCase } from "@/components/ui/representative-live-case";
import {
  buildResearchRecordMemo,
  downloadResearchRecordMemo,
  researchRecordExportReady,
  researchRecordMemoInput,
} from "@/lib/research-record-memo";
import {
  EVIDENCE_GLOSSARY,
  buildEvidenceVerificationManifest,
} from "@/lib/evidence-reader-guide";
import { RESEARCH_FINDINGS as F } from "@/lib/research-findings";
import {
  ACCEPTED_CORPUS as AC,
  DENOMINATOR_LEDGER,
  FAMILY_COVERAGE as FC,
} from "@/lib/accepted-corpus";
import { MECHANISM_FAMILY_EVIDENCE as MFE } from "@/lib/mechanism-family-evidence";
import { REPRESENTATIVE_CASE_LIBRARY as RCL } from "@/lib/representative-case-library";
import { EFFECTIVE_INDEPENDENT_EVIDENCE as EIE } from "@/lib/effective-independent-evidence";

// ---------------------------------------------------------------------------
// Stable research-section anchors (M1, extended by N2) — the page is
// directly addressable at /evidence, and exactly these five sections carry
// stable IDs a reviewer can link to (page header, canonical denominator
// ledger, Mission G record, Mission I record, Mission J record).  The IDs
// live on the existing section wrappers — which render in loading and
// unavailable states too — so an anchor never disappears while a record
// resolves.  Scrolling is bounded and injectable: known IDs scroll (offset
// for the sticky TopBar via scroll-mt), unknown hashes fail quietly, and
// the hashchange listener cleans up StrictMode-safe.
// ---------------------------------------------------------------------------

export const EVIDENCE_ANCHOR_IDS = [
  "evidence-top",
  "denominators",
  "mission-g",
  "mission-i",
  "mission-j",
  "event-dossiers",
] as const;

export function scrollToEvidenceHash(
  hash: string,
  doc: Pick<Document, "getElementById">,
): boolean {
  const id = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!id || !(EVIDENCE_ANCHOR_IDS as readonly string[]).includes(id)) {
    return false;
  }
  const el = doc.getElementById(id);
  if (!el) return false;
  el.scrollIntoView({ block: "start" });
  return true;
}

type HashScrollWindow = {
  location: { hash: string };
  addEventListener(type: "hashchange", listener: () => void): void;
  removeEventListener(type: "hashchange", listener: () => void): void;
};

/** Scroll the direct-entry hash once after mount, then follow hash changes
 *  while the page stays active; returns the listener cleanup. */
export function installEvidenceHashScroll(
  win: HashScrollWindow,
  doc: Pick<Document, "getElementById">,
): () => void {
  const scroll = () => {
    scrollToEvidenceHash(win.location.hash, doc);
  };
  scroll();
  win.addEventListener("hashchange", scroll);
  return () => win.removeEventListener("hashchange", scroll);
}

function Kicker({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-on-surface-variant/55">{children}</p>
  );
}

function Section({ tag, title, children }: { tag: string; title: string; children: React.ReactNode }) {
  return (
    <Card className="overflow-hidden border-border/50 bg-surface-container-low">
      <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
        <Kicker>{tag}</Kicker>
        <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
          {title}
        </h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
        {children}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/30 py-1 last:border-0">
      <span className="text-on-surface-variant/75">{label}</span>
      <span className="font-mono tabular-nums text-on-surface">{value}</span>
    </div>
  );
}

function Verdict({ children }: { children: React.ReactNode }) {
  return (
    <span className="w-fit rounded-full border border-border bg-surface-container px-2 py-0.5 font-mono text-[11px] tabular-nums text-on-surface-variant">
      {children}
    </span>
  );
}

// D1 — the canonical denominator funnel lives in the shared
// DENOMINATOR_LEDGER (lib/accepted-corpus): composed from the accepted-corpus
// constants (no number retyped) and consumed by BOTH this page and the M2
// research-record memo export, so the two renderings cannot drift.  Each step
// is a DIFFERENT denominator answering a DIFFERENT question — not a competing
// estimate of one number.

export function EvidenceOverview({
  onAnalyze,
}: {
  /** Opens the normal saved-analysis experience (numeric reopen); supplied
   *  by the App shell.  Absent in isolated renders — the band then shows
   *  the case without a navigation action. */
  onAnalyze?: (headline: string, opts: { eventId: number }) => void;
} = {}) {
  // H3 — Mission G record from the tracked-only GET /evidence/mission-g
  // contract. Long staleTime: the payload only changes on a tracked commit.
  const {
    data: missionG,
    isError: missionGError,
    isPending: missionGPending,
  } = useQuery({
    queryKey: qk.missionGEvidence(),
    queryFn: () => api.missionGEvidence(),
    staleTime: 1_800_000,
  });

  // N2 — Mission I ordinary-period comparison record from the tracked-only
  // GET /evidence/mission-i contract (restored by N1). One query; its
  // result is reused by the card, the memo export, and the reviewer guide.
  // Long staleTime: the payload only changes on a tracked commit.
  const {
    data: missionI,
    isError: missionIError,
    isPending: missionIPending,
  } = useQuery({
    queryKey: qk.missionIEvidence(),
    queryFn: () => api.missionIEvidence(),
    staleTime: 1_800_000,
  });

  // Mission J flagship — the published robustness/transmission record from
  // the tracked-only GET /evidence/mission-j contract. Long staleTime: the
  // payload only changes on a tracked commit.
  const {
    data: missionJ,
    isError: missionJError,
    isPending: missionJPending,
  } = useQuery({
    queryKey: qk.missionJEvidence(),
    queryFn: () => api.missionJEvidence(),
    staleTime: 1_800_000,
  });

  // U1 — universal event dossier index from the tracked-only
  // GET /evidence/event-dossiers contract. Index only: no dossier detail
  // is fetched until the reviewer opens an event inside the card. Long
  // staleTime: the payload only changes on a tracked commit.
  const {
    data: dossierIndex,
    isError: dossierIndexError,
    isPending: dossierIndexPending,
  } = useQuery({
    queryKey: qk.eventDossierIndex(),
    queryFn: () => api.eventDossierIndex(),
    staleTime: 1_800_000,
  });

  // M1 — direct-entry hash scroll (a mount at /evidence#mission-j lands on
  // the Mission J record) plus hash changes while the page stays active.
  useEffect(() => installEvidenceHashScroll(window, document), []);

  // N2/U1 — re-apply the direct-entry hash once the fetched records above
  // the target settle: the cards grow as they resolve, so the one-shot
  // mount scroll can land short of the anchor. Still bounded to the known
  // anchor IDs; an unknown or absent hash stays a no-op.
  const missionRecordsSettled =
    !missionGPending &&
    !missionIPending &&
    !missionJPending &&
    !dossierIndexPending;
  useEffect(() => {
    if (missionRecordsSettled) {
      scrollToEvidenceHash(window.location.hash, document);
    }
  }, [missionRecordsSettled]);

  // Shared M2/M3 snapshots of the three existing Mission queries — the
  // export action and the reviewer guide both read these; neither makes a
  // request.
  const missionGSnapshot = {
    isPending: missionGPending,
    isError: missionGError,
    data: missionG,
  };
  const missionISnapshot = {
    isPending: missionIPending,
    isError: missionIError,
    data: missionI,
  };
  const missionJSnapshot = {
    isPending: missionJPending,
    isError: missionJError,
    data: missionJ,
  };

  // M2 — one canonical research-record export, built ONLY on click from the
  // same canonical static constants and the same settled Mission G/I/J query
  // results this page renders (no rebuild per render, no second fetch, no
  // blob allocation outside the handler).  Ready once all three contracts
  // settle; a settled error exports as an explicitly unavailable lane.
  const exportReady = researchRecordExportReady(
    missionGSnapshot,
    missionISnapshot,
    missionJSnapshot,
  );
  const handleDownloadResearchRecord = () => {
    if (!exportReady) return;
    const markdown = buildResearchRecordMemo(
      researchRecordMemoInput(
        missionGSnapshot,
        missionISnapshot,
        missionJSnapshot,
        new Date().toISOString(),
      ),
    );
    downloadResearchRecordMemo(markdown);
  };

  // M3 — reviewer guide manifest: the five material evidence lanes traced to
  // their canonically recorded provenance, with pending / unavailable
  // contract lanes stated honestly (never omitted).
  const verificationLanes = buildEvidenceVerificationManifest(
    missionGSnapshot,
    missionISnapshot,
    missionJSnapshot,
  );

  return (
    <div className="mx-auto w-full max-w-5xl">
      {/* Header + purpose + non-claim banner + quiet export action */}
      <header id="evidence-top" className="mb-5 scroll-mt-20">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
          <div>
            <Kicker>Research</Kicker>
            <h1 className="mt-1 font-headline text-[22px] font-bold leading-tight tracking-[-0.01em] text-on-surface">
              Evidence Overview
            </h1>
          </div>
          <div className="flex flex-col items-start gap-1 pt-1 sm:items-end">
            <button
              type="button"
              disabled={!exportReady}
              onClick={handleDownloadResearchRecord}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-container px-2.5 py-1 font-mono text-[11px] text-on-surface-variant transition-colors hover:text-on-surface disabled:cursor-default disabled:opacity-50 disabled:hover:text-on-surface-variant"
            >
              <Download aria-hidden className="h-3 w-3" />
              Download research record (.md)
            </button>
            {!exportReady && (
              <p className="font-mono text-[10px] text-on-surface-variant/55">
                Preparing tracked evidence…
              </p>
            )}
          </div>
        </div>
        <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-on-surface-variant/85">
          This page summarizes descriptive archive evidence and the baseline checks behind it. It is
          not a trading or prediction surface, and it makes no claim of edge or statistical
          significance. Figures are read-only; each evidence surface below carries its own
          frozen or tracked provenance, and dated snapshots are labeled per section.
        </p>
      </header>

      {/* A4 — Representative Live Case: one restrained orientation band
          between the introduction and the reviewer guide.  Resolves the one
          published live case from its immutable candidate identity through
          the provider-free orientation read; links to the normal saved
          analysis; renders explicit unavailable states.  Product framing —
          never pooled with the evidence lanes below and never a research
          conclusion. */}
      <div className="mb-3">
        <RepresentativeLiveCase onOpenAnalysis={onAnalyze} />
      </div>

      {/* M3 — reviewer guide: one compact native disclosure, collapsed by
          default, between the page introduction and the denominator ledger.
          Two subsections only: the four-lane verification path (canonical
          provenance and inert reproduction commands; pending / unavailable
          contract lanes stated, never omitted) and the eight-term frozen
          claim-ceiling glossary sourced from the tracked J0/J2 contracts.
          The glossary's claim boundaries are the page's dedicated negated
          non-claim list. No new route, anchor, request, or download action. */}
      <details className="group mb-3 overflow-hidden rounded-md border border-border/50 bg-surface-container-low">
        <summary className="flex cursor-pointer list-none items-baseline justify-between gap-3 px-3.5 py-2.5 [&::-webkit-details-marker]:hidden">
          <span className="flex flex-col gap-0.5">
            <Kicker>Reviewer guide · provenance and definitions</Kicker>
            <span className="font-headline text-[13.5px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
              How to read and verify this record
            </span>
          </span>
          <span
            aria-hidden
            className="font-mono text-[10px] text-on-surface-variant/55 group-open:rotate-90"
          >
            ▸
          </span>
        </summary>
        <div className="flex flex-col gap-4 border-t border-border/40 px-3.5 py-3 text-[12.5px] leading-relaxed text-on-surface/85">
          {/* Subsection 1 — verification path */}
          <section className="flex flex-col gap-2">
            <Kicker>Verification path</Kicker>
            <p className="text-[11.5px] leading-relaxed text-on-surface-variant/75">
              Where each visible evidence lane comes from and how to reproduce or inspect it from a
              local checkout. Reproduction commands are inert reference text — nothing runs from
              this page, and fields the canonical sources do not record say so.
            </p>
            <div className="flex flex-col divide-y divide-border/30">
              {verificationLanes.map((lane) => (
                <div key={lane.lane} className="flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                    <span className="font-mono text-[11px] text-on-surface">{lane.lane}</span>
                    <span className="font-mono text-[10px] text-on-surface-variant/60">
                      {lane.availability}
                    </span>
                  </div>
                  <p className="text-[11.5px] leading-relaxed text-on-surface-variant/80">
                    {lane.purpose}
                  </p>
                  <p className="font-mono text-[10.5px] tabular-nums leading-relaxed text-on-surface-variant/70">
                    {lane.scope}
                  </p>
                  <dl className="flex flex-col gap-0.5 pt-0.5">
                    {lane.fields.map((f) => (
                      <div
                        key={f.label}
                        className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-3"
                      >
                        <dt className="w-56 shrink-0 text-[10.5px] text-on-surface-variant/60">
                          {f.label}
                        </dt>
                        <dd className="min-w-0 text-[11px] leading-relaxed text-on-surface-variant/85">
                          {f.code ? (
                            <code className="break-all font-mono text-[10.5px] text-on-surface-variant">
                              {f.value}
                            </code>
                          ) : (
                            f.value
                          )}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              ))}
            </div>
          </section>

          {/* Subsection 2 — terms and claim ceilings */}
          <section className="flex flex-col gap-2 border-t border-border/40 pt-3">
            <Kicker>Terms and claim ceilings</Kicker>
            <p className="text-[11.5px] leading-relaxed text-on-surface-variant/75">
              The frozen research states and evidence classes used above, with what each does not
              license. Definitions follow the tracked contracts; claim boundaries are stated per
              term.
            </p>
            <dl className="flex flex-col divide-y divide-border/30">
              {EVIDENCE_GLOSSARY.map((e) => (
                <div key={e.term} className="flex flex-col gap-0.5 py-2 first:pt-0 last:pb-0">
                  <dt className="font-mono text-[11px] text-on-surface">{e.term}</dt>
                  <dd className="flex flex-col gap-0.5">
                    <p className="text-[11.5px] leading-relaxed text-on-surface-variant/85">
                      {e.definition}
                    </p>
                    <p className="text-[11px] italic leading-relaxed text-on-surface-variant/70">
                      {e.boundary}
                    </p>
                    <p className="font-mono text-[10px] leading-relaxed text-on-surface-variant/50">
                      {e.source} · {e.sourceSection}
                    </p>
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        </div>
      </details>

      {/* D1 — canonical denominator ledger / evidence funnel.  A single anchor
          for the project's denominator accounting so the figures in the cards
          below read as answers to different questions, not as competing
          estimates of one unstable number.  All figures are the current
          accepted-lens snapshot (AC.restatedOn), recomputed read-only by
          scripts/stat_validation_readiness_report.py --lens accepted and
          scripts/event_study_coverage_report.py. */}
      <Card id="denominators" className="mb-3 scroll-mt-20 overflow-hidden border-border/50 bg-surface-container-low">
        <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
          <Kicker>Denominator ledger · evidence funnel</Kicker>
          <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
            Canonical denominators
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
          <p className="text-on-surface-variant/80">
            {`Each step is a different denominator answering a different question — not competing ` +
              `estimates of one number. Current accepted-lens snapshot as of ${AC.restatedOn}.`}
          </p>
          <ol className="flex flex-col">
            {DENOMINATOR_LEDGER.map((row, i) => (
              <li
                key={row.label}
                className="flex items-baseline gap-3 border-b border-border/30 py-1.5 last:border-0"
              >
                <span className="w-4 shrink-0 font-mono text-[10px] tabular-nums text-on-surface-variant/45">
                  {i + 1}
                </span>
                <span className="w-[4.5rem] shrink-0 font-mono text-[13px] tabular-nums text-on-surface">
                  {row.value}
                </span>
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="text-on-surface">{row.label}</span>
                  <span className="text-[11px] text-on-surface-variant/70">{row.note}</span>
                </span>
              </li>
            ))}
          </ol>
          {/* The two named outcome ledgers over the 86 accepted rows — same
              denominator, different semantics, never merged. The independence
              caution stays upstream: see the effective-independent-evidence
              card directly below before reading either split as separate
              evidence. */}
          <div className="flex flex-col gap-1 border-t border-border/40 pt-2">
            <p className="text-[11px] leading-relaxed text-on-surface-variant/70">
              Read both ledgers as clustered evidence — the effective-independent-evidence card
              below shows the 86 rows collapse into 7 market-story clusters.
            </p>
            <p className="font-mono text-[11px] tabular-nums text-on-surface-variant/80">
              {`${AC.orRuleName} (db.compute_track_record): ${AC.anySupporting} any-supporting / ` +
                `${AC.contradicted} contradicted / ${AC.unresolved} unresolved.`}
            </p>
            <p className="font-mono text-[11px] tabular-nums text-on-surface-variant/80">
              {`${AC.directionalMajority.ruleName}: ${AC.directionalMajority.validated} validated / ` +
                `${AC.directionalMajority.contradicted} contradicted / ` +
                `${AC.directionalMajority.unresolved} unresolved — ` +
                `${AC.directionalMajority.tieNote}.`}
            </p>
            <p className="text-[11px] leading-relaxed text-on-surface-variant/70">
              {`${AC.lensDivergenceNote} The majority labels are the production scorer's ` +
                `vocabulary — evidence sufficiency, not a success verdict and not a claim ` +
                `about future events.`}
            </p>
          </div>
          <p className="text-[11.5px] italic leading-relaxed text-on-surface-variant/75">
            Staged candidates sit outside the accepted and FDR pools and never enter accepted
            denominators or claims. Event-study availability is a coverage denominator, not a
            significance claim; representative cases are illustrative, not evidence.
          </p>
        </CardContent>
      </Card>

      {/* H3 — the completed Mission G historical research record, consumed
          from the tracked-artifact-backed GET /evidence/mission-g contract
          (H2). Placed directly under the denominator ledger so the second
          evidence lane appears where denominators are introduced. The
          accepted-lane result above answers a directional-skill /
          above-baseline question over the 86 accepted rows; Mission G
          answers a historical state-conditioning question over its own
          97-event ledger — different questions, never pooled. */}
      <Card id="mission-g" className="mb-3 scroll-mt-20 overflow-hidden border-border/50 bg-surface-container-low">
        <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
          <Kicker>Historical evidence · Mission G · separate ledger</Kicker>
          <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
            Mission G historical research record
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
          <p className="text-on-surface-variant/80">
            A frozen-design historical program, separate from the accepted
            track record above: it asks whether pre-event market state
            conditioned event reactions across two bounded historical
            universes, not whether the live archive shows above-baseline
            directional skill. All figures below are served from the tracked
            research artifacts.
          </p>
          <MissionGEvidenceCard
            data={missionG}
            unavailable={missionGError}
          />
        </CardContent>
      </Card>

      {/* N2 — the published Mission I ordinary-period comparison record,
          consumed from the tracked-publication-backed
          GET /evidence/mission-i contract (restored by N1). Placed between
          the Mission G and Mission J records — the project's research
          chain reads: what happened across historical states (G) → was the
          event-window magnitude unusual versus ordinary periods (I) → did
          the inherited FOMC result survive new robustness challenges (J).
          Three separate ledgers with separate denominators; their numbers
          are never pooled and never staged as one statistical sample. All
          research values, states, headlines, falsifiers and non-claims
          come verbatim from the contract. */}
      <Card id="mission-i" className="mb-3 scroll-mt-20 overflow-hidden border-border/50 bg-surface-container-low">
        <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
          <Kicker>Ordinary-period comparison · Mission I · separate ledger</Kicker>
          <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
            Were these event windows unusual relative to ordinary periods?
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
          <p className="text-on-surface-variant/80">
            A frozen descriptive comparison, separate from Mission G above
            and Mission J below: it asks whether the completed FOMC and
            OPEC event windows were unusual in response magnitude relative
            to eligible ordinary non-event periods on the same frozen
            assets, response metrics, horizons, and calculation rules. The
            two families keep separate ledgers, no result is pooled, and
            there are no p-values and no pooled FDR family. All figures
            below are served from the seven tracked Mission I publications.
          </p>
          <MissionIEvidenceCard
            data={missionI}
            unavailable={missionIError}
          />
        </CardContent>
      </Card>

      {/* Mission J flagship — the published FOMC robustness & transmission
          record, consumed from the tracked-publication-backed
          GET /evidence/mission-j contract. Placed directly after the
          Mission I record: a separate frozen research program with its own
          denominators (never pooled with Mission G, Mission I, or the
          accepted track record). Editorial treatment translated from the
          Executive Design package; all research values, states, qualifiers
          and non-claims come verbatim from the contract. */}
      <Card id="mission-j" className="mb-3 scroll-mt-20 overflow-hidden border-border/50 bg-surface-container-low">
        <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
          <Kicker>Robustness record · Mission J · separate ledger</Kicker>
          <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
            Mission J — FOMC robustness &amp; transmission record
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
          <p className="text-on-surface-variant/80">
            A hindsight-controlled robustness program over the completed
            FOMC 1d finding: a prospectively frozen constitution (J0), a
            frozen data substrate (J1A), an asset-and-benchmark challenge
            (J1B), a timing and exact-window collision challenge (J2), and
            a frozen mechanism/transmission readout (J3). Same-sample Class
            B evidence under prospectively frozen new tests — never
            independent historical confirmation. All figures below are
            served from the tracked research publications.
          </p>
          <MissionJEvidenceCard
            data={missionJ}
            unavailable={missionJError}
          />
        </CardContent>
      </Card>

      {/* U1 — the universal event dossier reader over the complete
          published 97-event historical universe, consumed from the
          tracked-only GET /evidence/event-dossiers[/{id}] contracts (U0).
          Placed after the three aggregate mission records: the chain reads
          what happened across historical states (G) → was the event-window
          magnitude unusual (I) → did the FOMC reading survive robustness
          challenges (J) → the per-event record behind all of it, one
          dossier per event. Publication order only; the card fetches one
          dossier at a time on open and never ranks, selects, or features
          an event. FOMC and OPEC remain separate ledgers. */}
      <Card id="event-dossiers" className="mb-3 scroll-mt-20 overflow-hidden border-border/50 bg-surface-container-low">
        <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
          <Kicker>Universal event dossiers · complete historical universe</Kicker>
          <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
            Universal event dossiers
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
          <p className="text-on-surface-variant/80">
            One dossier per published historical event — identity and
            source, exact denominators, mechanism and asset basis, the
            per-event observations, ordinary-period context, robustness,
            falsifier and fragility context, missingness, provenance, and
            claim ceilings. Every figure is served verbatim from the
            tracked publications; opening an event fetches its single
            dossier and nothing else.
          </p>
          <UniversalEventDossiersCard
            data={dossierIndex}
            unavailable={dossierIndexError}
          />
        </CardContent>
      </Card>

      {/* K3B — surface of the read-only K2 effective-independent-evidence
          report. Static snapshot from EFFECTIVE_INDEPENDENT_EVIDENCE (no browser
          recompute, no network); figures trace to
          stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md @ EIE.sourceCommit. Placed
          directly under the denominator ledger so the independence caution lands
          where the 86 accepted track-record rows are introduced. Descriptive
          independence-caution layer, not an inferential effective sample size. */}
      <Card className="mb-3 overflow-hidden border-border/50 bg-surface-container-low">
        <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
          <Kicker>Effective independent evidence · independence caution</Kicker>
          <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
            Effective independent evidence
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
          <p className="text-on-surface-variant/80">
            {`The ${EIE.acceptedTrackRecordRows} accepted track-record rows group into ` +
              `${EIE.clusterCount} descriptive market-story clusters under transparent ` +
              `same-date / same-primary-ticker-window / duplicate-link rules. The largest ` +
              `cluster holds ${EIE.largestClusterRows} rows and ` +
              `${EIE.representativeCasesInLargest} / ${EIE.representativeCasesTotal} representative cases.`}
          </p>

          <div className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] tabular-nums text-on-surface-variant/80">
            <span>accepted track-record rows <span className="text-on-surface">{EIE.acceptedTrackRecordRows}</span></span>
            <span>market-story clusters <span className="text-on-surface">{EIE.clusterCount}</span></span>
            <span>largest cluster <span className="text-on-surface">{EIE.largestClusterRows} rows</span></span>
            <span>representative cases in largest <span className="text-on-surface">{EIE.representativeCasesInLargest} / {EIE.representativeCasesTotal}</span></span>
          </div>

          <p className="text-on-surface/80">
            {`Read the support / contradiction / unresolved counts as clustered evidence — a ` +
              `small number of market tapes observed many ways — not ` +
              `${EIE.acceptedTrackRecordRows} separate market stories.`}
          </p>

          <p className="text-[11.5px] italic leading-relaxed text-on-surface-variant/75">
            Descriptive independence-caution only — not an inferential effective sample size,
            score, rank, p-value, or FDR pool, and not a trading, prediction, or recommendation
            surface.
          </p>

          <p className="font-mono text-[10px] leading-relaxed text-on-surface-variant/55">
            {`Surface of the read-only K2 report · source ${EIE.sourceDoc} @ ${EIE.sourceCommit} · ${EIE.reproCommand}`}
          </p>
        </CardContent>
      </Card>

      {/* E2 — surface of the read-only E1 mechanism-family evidence inventory.
          Static snapshot from MECHANISM_FAMILY_EVIDENCE (no browser recompute,
          no network); every figure traces to stats/MECHANISM_FAMILY_EVIDENCE_INVENTORY.md
          @ MFE.sourceCommit. Family lens = the tested headline overlay over the
          86 accepted thesis rows (per-family event-study is k-of-n on THAT lens,
          distinct from the 78/94 coverage lens above). Descriptive inventory,
          not family-level inference. */}
      <Card className="mb-3 overflow-hidden border-border/50 bg-surface-container-low">
        <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
          <Kicker>Mechanism families · evidence inventory</Kicker>
          <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
            Mechanism-family evidence inventory
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
          <p className="text-on-surface-variant/80">
            {`Accepted track-record lens: ${MFE.buckets.sum} rows grouped by the tested headline ` +
              `overlay. Family rows are descriptive inventory, not family-level inference.`}
          </p>
          <p className="text-[11px] leading-relaxed text-on-surface-variant/70">
            {`Different denominator from the "Mechanism-family grouping" card (a different keyword ` +
              `rule set over the 81 market-scored snapshot) and the "Mechanism-family coverage" ` +
              `card (stored-taxonomy observations) below — different lenses, not competing estimates ` +
              `of one count.`}
          </p>

          <div className="overflow-hidden rounded-md border border-border/40">
            <table className="w-full text-left font-mono text-[11px] tabular-nums">
              <thead>
                <tr className="border-b border-border/40 bg-surface-container-highest/40 text-on-surface-variant/60">
                  <th className="px-2.5 py-1.5 font-medium">Family</th>
                  <th className="px-2.5 py-1.5 text-right font-medium">n</th>
                  <th className="px-2.5 py-1.5 text-right font-medium">S / C / U</th>
                  <th className="px-2.5 py-1.5 text-right font-medium">event-study</th>
                  <th className="px-2.5 py-1.5 font-medium">sector hint</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {MFE.families.map((f) => (
                  <tr key={f.family}>
                    <td className="px-2.5 py-1.5 text-on-surface">
                      {f.family}
                      {f.overlayOnly && (
                        <span className="ml-1.5 text-[10px] text-on-surface-variant/55">overlay-only</span>
                      )}
                      {f.thin && (
                        <span className="ml-1.5 text-[10px] text-on-surface-variant/55">thin family</span>
                      )}
                    </td>
                    <td className="px-2.5 py-1.5 text-right text-on-surface">{f.n}</td>
                    <td className="px-2.5 py-1.5 text-right text-on-surface">{`${f.s} / ${f.c} / ${f.u}`}</td>
                    <td className="px-2.5 py-1.5 text-right text-on-surface-variant">{`${f.esAvailable} / ${f.esOf}`}</td>
                    <td className="px-2.5 py-1.5 text-on-surface-variant/85">{f.sector}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="font-mono text-[11px] tabular-nums text-on-surface-variant/75">
            {`single-match ${MFE.buckets.singleMatch} · multi-match ${MFE.buckets.multiMatch} · ` +
              `unclassified ${MFE.buckets.unclassified} = ${MFE.buckets.sum}`}
          </p>

          {/* Representative case ids — illustrative only, not evidence. */}
          <div className="flex flex-col gap-1 border-t border-border/40 pt-2">
            <Kicker>Illustrative case ids</Kicker>
            <ul className="flex flex-col gap-0.5">
              {MFE.families.map((f) => (
                <li key={f.family} className="flex items-baseline justify-between gap-3 text-[11px]">
                  <span className="text-on-surface-variant/85">{f.family}</span>
                  <span className="font-mono tabular-nums text-on-surface-variant">{f.caseIds.join(", ")}</span>
                </li>
              ))}
            </ul>
            <p className="text-[11px] italic text-on-surface-variant/70">
              Illustrative case ids only — representative of a family, not evidence for it.
            </p>
          </div>

          {/* Caveats */}
          <ul className="flex flex-col gap-1 border-t border-border/40 pt-2">
            {[
              "Family lens is the headline overlay, not the stored mechanism_family taxonomy.",
              `Overlay-only buckets (outside the canonical taxonomy): ${MFE.families
                .filter((f) => f.overlayOnly)
                .map((f) => f.family)
                .join(", ")}.`,
              `Multi-match (${MFE.buckets.multiMatch}) and unclassified (${MFE.buckets.unclassified}) rows stay visible, not absorbed.`,
              "Staged candidates are excluded from this accepted track-record lens.",
              "Sectors are descriptive hints only; SPY stays the canonical benchmark.",
              "No family-level causal claim, no p-values, and no FDR here.",
            ].map((line) => (
              <li
                key={line}
                className="flex items-start gap-1.5 text-[11px] leading-relaxed text-on-surface-variant/70"
              >
                <span className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-on-surface-variant/40" aria-hidden />
                {line}
              </li>
            ))}
          </ul>

          <p className="font-mono text-[10px] leading-relaxed text-on-surface-variant/55">
            {`Surface of the read-only E1 report · source ${MFE.sourceDoc} @ ${MFE.sourceCommit} · ${MFE.reproCommand}`}
          </p>
        </CardContent>
      </Card>

      {/* F3 — surface of the F1/F2 representative research set. Static snapshot
          from REPRESENTATIVE_CASE_LIBRARY (no browser recompute, no network);
          the SELECTION traces to stats/REPRESENTATIVE_CASE_EXPANSION.md (F1)
          and stats/EXPANDED_CASE_NOTES.md (F2) @ RCL.sourceCommit; outcomes
          were restated from the current archive on RCL.outcomesRestatedOn.
          The 6 N1 anchors are already-covered (kept in the transmission
          walkthrough, not rewritten here); the 9 new cases have expanded F2
          notes. A DIFFERENT list from the app Case Library's editorial
          walkthrough. */}
      <Card className="mb-3 overflow-hidden border-border/50 bg-surface-container-low">
        <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
          <Kicker>Representative cases · frozen F1 selection rule</Kicker>
          <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
            F1/F2 representative research set
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
          <p className="text-on-surface-variant/80">
            {`${RCL.totals.total} illustrative cases across ${RCL.totals.familiesTotal} mechanism families: `}
            {`${RCL.totals.anchors} already-covered N1 anchors + ${RCL.totals.newNotes} newly proposed F1/F2 cases, `}
            {`selected under the frozen F1 selection rule — not the app Case Library walkthrough, which is a `}
            {`separate editorial slate. Selection is frozen @ ${RCL.sourceCommit}; outcomes restated ${RCL.outcomesRestatedOn} `}
            {`from the current archive. Representative cases are for walkthrough depth, not family-level `}
            {`inference, and neither list stands in for the corpus-level evidence.`}
          </p>

          <div className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] tabular-nums text-on-surface-variant/80">
            <span>total <span className="text-on-surface">{RCL.totals.total}</span></span>
            <span>anchors <span className="text-on-surface">{RCL.totals.anchors}</span></span>
            <span>new notes <span className="text-on-surface">{RCL.totals.newNotes}</span></span>
            <span>event-study readout <span className="text-on-surface">{RCL.totals.eventStudyAvailable} / {RCL.totals.eventStudyOf}</span></span>
            <span>families <span className="text-on-surface">{RCL.totals.familiesRepresented} / {RCL.totals.familiesTotal}</span></span>
          </div>

          <div className="overflow-hidden rounded-md border border-border/40">
            <table className="w-full text-left font-mono text-[11px] tabular-nums">
              <thead>
                <tr className="border-b border-border/40 bg-surface-container-highest/40 text-on-surface-variant/60">
                  <th className="px-2.5 py-1.5 font-medium">Case</th>
                  <th className="px-2.5 py-1.5 font-medium">Role</th>
                  <th className="px-2.5 py-1.5 font-medium">Family</th>
                  <th className="px-2.5 py-1.5 font-medium">Outcome</th>
                  <th className="px-2.5 py-1.5 font-medium">Event-study</th>
                  <th className="px-2.5 py-1.5 font-medium">Caveats</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {RCL.cases.map((c) => (
                  <tr key={c.id}>
                    <td className="px-2.5 py-1.5 text-on-surface">#{c.id}</td>
                    <td className="px-2.5 py-1.5 text-on-surface-variant/85">
                      {c.role === "anchor" ? "already-covered anchor" : "newly proposed"}
                    </td>
                    <td className="px-2.5 py-1.5 text-on-surface-variant/85">{c.family}</td>
                    <td className="px-2.5 py-1.5 text-on-surface">{c.outcome}</td>
                    <td className="px-2.5 py-1.5 text-on-surface-variant">{c.eventStudy ? "yes" : "no"}</td>
                    <td className="px-2.5 py-1.5 text-[10px] text-on-surface-variant/70">
                      {c.caveats.length ? c.caveats.join(" · ") : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-[11.5px] italic leading-relaxed text-on-surface-variant/75">
            Readout availability is not the same as thesis support. Outcome is thesis-direction
            scoring of the named tickers; the event-study readout is the primary ticker vs SPY - a
            different lens (cases 29 and 38 share a readout but have opposite outcomes).
          </p>

          <p className="font-mono text-[10px] leading-relaxed text-on-surface-variant/55">
            {`Source: ${RCL.sources[0]} and ${RCL.sources[1]} @ ${RCL.sourceCommit}. ` +
              `N1 anchors stay in the transmission walkthrough; the 9 new cases have expanded notes.`}
          </p>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {/* Corpus snapshot — the dated F.asOf figures, with the current
            post-AP3b restatement stated separately below (the T2/T3/T4
            baselines are an as-of-F.asOf snapshot and are not recomputed here,
            so the snapshot figures stay at their real date). */}
        <Section tag="Corpus" title="Scored-archive snapshot">
          <p className="text-[11px] text-on-surface-variant/70">
            {`Snapshot as of ${F.asOf} (pre-restatement · superseded — AP3b-era; see the ` +
              `canonical denominators above):`}
          </p>
          <Stat label="Market-scored events" value={F.corpus.marketScored} />
          <Stat label="Any-supporting" value={F.corpus.anySupporting} />
          <Stat label="Contradicted" value={F.corpus.contradicted} />
          <Stat label="Unresolved" value={F.corpus.unresolved} />
          <Stat label="Event-study available" value={F.corpus.eventStudyAvailable} />
          <Stat label="Event-study unavailable" value={F.corpus.eventStudyUnavailable} />
          <p className="border-t border-border/40 pt-2 text-[12px] leading-relaxed text-on-surface/85">
            {`Restated ${AC.restatedOn} (post-recovery): the live archive now holds ${AC.savedEvents} saved events; ` +
              `the accepted track-record corpus is ${AC.trackRecordTotal} — ` +
              `${AC.orRuleName}: ${AC.anySupporting} any-supporting / ${AC.contradicted} contradicted / ` +
              `${AC.unresolved} unresolved — and the coverage / analysis denominator is ` +
              `${AC.coverageDenominator}, after ${AC.syntheticSeedFlagged} synthetic/test seed rows were ` +
              `flagged in event_hygiene and excluded (kept in the archive, never deleted; AP3b). ` +
              `Phase 1 and Phase 2 remain separate pools.`}
          </p>
        </Section>

        {/* T2A baseline */}
        <Section tag="T2A · marginal-preserving baseline" title="Raw outcomes vs a naive baseline">
          <Stat label="Observed validated" value={F.t2aBaseline.observedValidated} />
          <Stat label="Null mean" value={F.t2aBaseline.nullMean} />
          <Stat label="95% interval" value={F.t2aBaseline.ci95} />
          <div className="flex items-center gap-2 pt-1">
            <span className="text-on-surface-variant/75">Verdict</span>
            <Verdict>{F.t2aBaseline.verdict}</Verdict>
          </div>
          <p className="text-on-surface/80">{F.t2aBaseline.interpretation}</p>
        </Section>

        {/* T2B primary-only AR-sign */}
        <Section tag="T2B · primary-only AR-sign" title="Benchmark-adjusted, primary ticker only">
          <Stat label="Benchmark" value={F.t2bPrimary.benchmark} />
          <Stat label="Eligible observations / horizon" value={F.t2bPrimary.eligiblePerHorizon} />
          <Stat label="Support · 1d / 5d / 20d" value={`${F.t2bPrimary.support["1d"]} / ${F.t2bPrimary.support["5d"]} / ${F.t2bPrimary.support["20d"]}`} />
          <div className="flex items-center gap-2 pt-1">
            <span className="text-on-surface-variant/75">Reliability</span>
            <Verdict>{F.t2bPrimary.reliability}</Verdict>
          </div>
          <p className="text-on-surface/80">{F.t2bPrimary.reason}</p>
        </Section>

        {/* T3A multi-ticker AR */}
        <Section tag="T3A · multi-ticker AR-sign" title="Benchmark-adjusted, all affected names">
          <Stat label="Eligible ticker observations" value={F.t3aMulti.eligibleObs} />
          <Stat label="Eligible events" value={F.t3aMulti.eligibleEvents} />
          <Stat label="Predicted-up marginal" value={F.t3aMulti.predictedUpMarginal} />

          <div className="mt-1 overflow-hidden rounded-md border border-border/40">
            <table className="w-full text-left font-mono text-[11px] tabular-nums">
              <thead>
                <tr className="border-b border-border/40 bg-surface-container-highest/40 text-on-surface-variant/60">
                  <th className="px-2.5 py-1.5 font-medium">Horizon</th>
                  <th className="px-2.5 py-1.5 text-right font-medium">Support</th>
                  <th className="px-2.5 py-1.5 text-right font-medium">Null mean</th>
                  <th className="px-2.5 py-1.5 text-right font-medium">95% interval</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {F.t3aMulti.horizons.map((hz) => (
                  <tr key={hz.h}>
                    <td className="px-2.5 py-1.5 text-on-surface">{hz.h}</td>
                    <td className="px-2.5 py-1.5 text-right text-on-surface">{hz.support}</td>
                    <td className="px-2.5 py-1.5 text-right text-on-surface-variant">{hz.nullMean}</td>
                    <td className="px-2.5 py-1.5 text-right text-on-surface-variant">{hz.ci}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-col gap-1 pt-1">
            <Verdict>{F.t3aMulti.verdict}</Verdict>
            <p className="text-[11px] italic text-on-surface-variant/70">{F.t3aMulti.reliability}</p>
          </div>
          <p className="text-on-surface/80">{F.t3aMulti.interpretation}</p>
        </Section>

        {/* T4A coverage limitation — full width */}
        <Card className="overflow-hidden border-[#ee7d77]/25 bg-surface-container-low lg:col-span-2">
          <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
            <Kicker>T4A · coverage (repaired)</Kicker>
            <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
              Exposed-name AR coverage — repaired (V2C)
            </h2>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
            <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-3">
              <Stat label="Beneficiary AR coverage" value={`${F.t4aCoverage.beneficiary} · ${F.t4aCoverage.beneficiaryPct}`} />
              <Stat label="Exposed / loser AR coverage" value={`${F.t4aCoverage.loser} · ${F.t4aCoverage.loserPct}`} />
              <Stat label="Total AR coverage" value={`${F.t4aCoverage.total} · ${F.t4aCoverage.totalPct}`} />
            </div>
            <p className="text-on-surface/80">{F.t4aCoverage.limitation}</p>
            <p className="text-[11.5px] italic text-on-surface-variant/75">{F.t4aCoverage.repairBoundary}</p>
          </CardContent>
        </Card>
      </div>

      {/* Mechanism families — deterministic inference (T7B-A) */}
      <Card className="mt-3 overflow-hidden border-border/50 bg-surface-container-low">
        <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
          <Kicker>Mechanism families · deterministic inference</Kicker>
          <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
            Mechanism-family grouping
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
          <p className="text-on-surface-variant/80">
            <span className="font-mono tabular-nums text-on-surface">
              {F.mechanismFamilies.nonNone} / {F.mechanismFamilies.scoredTotal}
            </span>{" "}
            scored events carry a deterministic family.
          </p>
          <ul className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
            {F.mechanismFamilies.families.map((fam) => (
              <li key={fam.id} className="flex items-baseline justify-between gap-3 border-b border-border/30 py-1">
                <span className="font-mono text-[12px] text-on-surface-variant/85">
                  {fam.id}{fam.id === "none" ? " / unclassified" : ""}
                </span>
                <span className="font-mono tabular-nums text-on-surface">{fam.count}</span>
              </li>
            ))}
          </ul>
          <p className="text-[11px] italic text-on-surface-variant/70">{F.mechanismFamilies.label}</p>
          <p className="text-[11px] italic text-on-surface-variant/70">{F.mechanismFamilies.caveat}</p>
        </CardContent>
      </Card>

      {/* Mechanism-family coverage — accepted vs staged separation (AZ1).
          Static dated snapshot from FAMILY_COVERAGE; the read-only report
          named below recomputes every figure. Staged candidates are review
          staging only and never enter accepted denominators. */}
      <Card className="mt-3 overflow-hidden border-border/50 bg-surface-container-low">
        <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
          <Kicker>Mechanism families · accepted vs staged</Kicker>
          <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
            Mechanism-family coverage
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
          <p className="text-on-surface-variant/80">
            {`The archive separates accepted evidence from staged no-paid candidates by mechanism `}
            {`family (as of ${FC.asOf}). Family labels are a research taxonomy, not a causal claim.`}
          </p>

          <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
            <Stat label="Coverage / analysis denominator" value={AC.coverageDenominator} />
            <Stat label="Accepted track-record denominator" value={AC.trackRecordTotal} />
            <Stat label="Staged candidates (excluded from accepted)" value={FC.stagedCandidates} />
            <Stat label="Accepted family-labeled rows" value={FC.acceptedFamilyLabeled} />
          </div>

          <p className="text-on-surface/80">
            {`The accepted family-labeled rows are all curated observations (no thesis outcome), and `}
            <span className="font-mono tabular-nums text-on-surface">{FC.untaggedAccepted}</span>
            {` accepted rows remain untagged — a data limitation this page states rather than hides.`}
          </p>

          <div className="flex flex-col gap-1 border-t border-border/40 pt-2">
            <p className="text-on-surface-variant/80">
              {`Staged-only families (zero accepted rows): `}
              <span className="font-mono text-[12px] text-on-surface">{FC.stagedOnlyFamilies}</span>
              {` — industrial_policy is staged with a weak event-date caveat (anticipated bill signings).`}
            </p>
            <ul className="flex flex-col">
              {FC.tier1.map((c) => (
                <li key={c.id} className="flex items-baseline justify-between gap-3 border-b border-border/30 py-1 last:border-0">
                  <span className="text-on-surface-variant/85">
                    <span className="font-mono text-[12px] text-on-surface">#{c.id}</span>
                    {` ${c.label}`}
                  </span>
                  <span className="font-mono text-[11px] text-on-surface-variant">{c.family} · staged</span>
                </li>
              ))}
            </ul>
          </div>

          <p className="text-[11.5px] italic text-on-surface-variant/75">
            Staged candidates are not accepted evidence and never enter accepted denominators;
            representative cases are illustrative, not evidence.
          </p>

          <p className="font-mono text-[11px] leading-relaxed text-on-surface-variant/70">
            {`Reproduce read-only: ${FC.reproCommand} · context: ${FC.overviewNote} · `}
            {`decisions: ${FC.shortlistNote}`}
          </p>
        </CardContent>
      </Card>

      {/* How to read the event-study rows (U2) — defines the per-horizon
          measures the EventDossier table displays.  Surfaces existing
          methodology only; adds no new statistic and no new claim. */}
      <Card className="mt-3 overflow-hidden border-border/50 bg-surface-container-low">
        <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
          <Kicker>Methodology · event-study readout</Kicker>
          <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
            How to read the event-study rows
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
          <p className="font-mono text-[11px] tabular-nums text-on-surface-variant/75">
            Benchmark {F.methodology.benchmark} · horizons {F.methodology.horizons} · estimation window{" "}
            {F.methodology.estimationWindow} pre-event bars
          </p>
          <p className="text-on-surface-variant/80">{F.methodology.intro}</p>
          <dl className="flex flex-col gap-1.5">
            {F.methodology.terms.map((t) => (
              <div key={t.term} className="flex flex-col gap-0.5 sm:flex-row sm:gap-3">
                <dt className="w-14 shrink-0 font-mono text-[12px] text-on-surface">{t.term}</dt>
                <dd className="text-[12px] text-on-surface-variant/85">{t.def}</dd>
              </div>
            ))}
          </dl>
          <ul className="flex flex-col gap-1 border-t border-border/40 pt-2">
            {F.methodology.limits.map((line) => (
              <li
                key={line}
                className="flex items-start gap-1.5 text-[11px] leading-relaxed text-on-surface-variant/70"
              >
                <span className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-on-surface-variant/40" aria-hidden />
                {line}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      {/* Coverage repair — EXECUTED (V2C).  The V2A worklist was backfilled on a
          DB copy and the additive price-cache rows were promoted into live after
          operator approval.  The figures below are the residual (still-missing)
          worklist; the live coverage above already reflects the repair. */}
      <Card className="mt-3 overflow-hidden border-border/50 bg-surface-container-low">
        <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
          <Kicker>Coverage repair · executed</Kicker>
          <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
            Coverage repair — executed (V2C)
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
          <p className="text-on-surface-variant/80">
            Live exposed/loser AR coverage is now{" "}
            <span className="font-mono tabular-nums text-on-surface">{F.coverageRepairPlan.liveLoser}</span>{" "}
            and total ticker-level AR coverage is{" "}
            <span className="font-mono tabular-nums text-on-surface">{F.coverageRepairPlan.liveTotal}</span>{" "}
            after promoting{" "}
            <span className="font-mono tabular-nums text-on-surface">{F.coverageRepairPlan.rowsInserted}</span>{" "}
            additive price-cache rows into live.
          </p>

          <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-3">
            <Stat label="Residual missing units" value={F.coverageRepairPlan.remaining.units} />
            <Stat label="Residual distinct symbols" value={F.coverageRepairPlan.remaining.distinctSymbols} />
            <Stat label="Residual windows" value={F.coverageRepairPlan.remaining.windows} />
          </div>

          <ul className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
            {F.coverageRepairPlan.fixability.map((f) => (
              <li key={f.id} className="flex items-baseline justify-between gap-3 border-b border-border/30 py-1">
                <span className="font-mono text-[12px] text-on-surface-variant/85">
                  {f.id}
                  <span className="ml-1.5 text-[10px] text-on-surface-variant/55">
                    {f.fixable ? "fixable" : "not-fixable"}
                  </span>
                </span>
                <span className="font-mono tabular-nums text-on-surface">{f.count}</span>
              </li>
            ))}
          </ul>

          <ul className="flex flex-col gap-1 border-t border-border/40 pt-2">
            {F.coverageRepairPlan.notes.map((line) => (
              <li
                key={line}
                className="flex items-start gap-1.5 text-[11px] leading-relaxed text-on-surface-variant/75"
              >
                <span className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-on-surface-variant/40" aria-hidden />
                {line}
              </li>
            ))}
          </ul>

          <p className="text-[11px] italic leading-relaxed text-on-surface-variant/70">
            {F.coverageRepairPlan.nonClaim}
          </p>
        </CardContent>
      </Card>

      {/* Standing non-claims */}
      <div className="mt-4 rounded-md border border-border/50 bg-surface-container-low px-3.5 py-3">
        <Kicker>What this is not</Kicker>
        <ul className="mt-2 flex flex-col gap-1">
          {F.nonClaims.map((line) => (
            <li key={line} className="flex items-start gap-1.5 text-[11.5px] leading-relaxed text-on-surface-variant/70">
              <span className={cn("mt-[6px] h-1 w-1 shrink-0 rounded-full bg-on-surface-variant/40")} aria-hidden />
              {line}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
