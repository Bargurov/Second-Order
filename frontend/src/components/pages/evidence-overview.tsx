/**
 * Evidence Overview (T5A) — a calm, app-native summary of the T2/T3/T4 baseline
 * research: the corpus snapshot, the marginal-preserving baseline (T2A), the
 * degenerate primary-only AR-sign (T2B), the multi-ticker AR result (T3A), and
 * the exposed-name coverage limitation (T4A).  Descriptive archive evidence —
 * not a trading or prediction surface; it adds no new analytics and no claims.
 *
 * Pure / presentational: it renders the static `RESEARCH_FINDINGS` snapshot.
 */
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { RESEARCH_FINDINGS as F } from "@/lib/research-findings";
import { ACCEPTED_CORPUS as AC, FAMILY_COVERAGE as FC } from "@/lib/accepted-corpus";
import { MECHANISM_FAMILY_EVIDENCE as MFE } from "@/lib/mechanism-family-evidence";
import { REPRESENTATIVE_CASE_LIBRARY as RCL } from "@/lib/representative-case-library";
import { EFFECTIVE_INDEPENDENT_EVIDENCE as EIE } from "@/lib/effective-independent-evidence";

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

// D1 — the canonical denominator funnel.  Every figure is composed from the
// shared accepted-corpus constants (no number is retyped here), so the ledger
// cannot drift from the cards below.  Each step is a DIFFERENT denominator
// answering a DIFFERENT question — not a competing estimate of one number.
const LEDGER: ReadonlyArray<{ value: React.ReactNode; label: string; note: string }> = [
  {
    value: AC.savedEvents,
    label: "archive rows",
    note: "Full local archive — every saved event, including flagged seeds and staged / pending rows.",
  },
  {
    value: AC.coverageDenominator,
    label: "accepted coverage rows",
    note: "Accepted rows eligible for coverage / event-date reporting.",
  },
  {
    value: AC.trackRecordTotal,
    label: "accepted track-record rows",
    note: "Accepted rows used for support / contradiction / unresolved accounting.",
  },
  {
    value: `${AC.eventStudyAvailable} / ${AC.coverageDenominator}`,
    label: "event-study available",
    note: "Accepted coverage rows with a SPY-relative event-study readout — a coverage denominator, not a significance claim.",
  },
  {
    value: FC.stagedCandidates,
    label: "staged candidates",
    note: "Outside the accepted and FDR pools; never merged into accepted claims.",
  },
];

export function EvidenceOverview() {
  return (
    <div className="mx-auto w-full max-w-5xl">
      {/* Header + purpose + non-claim banner */}
      <header className="mb-5">
        <Kicker>Research</Kicker>
        <h1 className="mt-1 font-headline text-[22px] font-bold leading-tight tracking-[-0.01em] text-on-surface">
          Evidence Overview
        </h1>
        <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-on-surface-variant/85">
          This page summarizes descriptive archive evidence and the baseline checks behind it. It is
          not a trading or prediction surface, and it makes no claim of edge or statistical
          significance. Figures are a read-only snapshot as of {F.asOf}.
        </p>
      </header>

      {/* D1 — canonical denominator ledger / evidence funnel.  A single anchor
          for the project's denominator accounting so the figures in the cards
          below read as answers to different questions, not as competing
          estimates of one unstable number.  All figures are the current
          accepted-lens snapshot (AC.restatedOn), recomputed read-only by
          scripts/stat_validation_readiness_report.py --lens accepted and
          scripts/event_study_coverage_report.py. */}
      <Card className="mb-3 overflow-hidden border-border/50 bg-surface-container-low">
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
            {LEDGER.map((row, i) => (
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
          <p className="text-[11.5px] italic leading-relaxed text-on-surface-variant/75">
            Staged candidates sit outside the accepted and FDR pools and never enter accepted
            denominators or claims. Event-study availability is a coverage denominator, not a
            significance claim; representative cases are illustrative, not evidence.
          </p>
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

      {/* F3 — surface of the F1/F2 representative case library. Static snapshot
          from REPRESENTATIVE_CASE_LIBRARY (no browser recompute, no network);
          figures trace to stats/REPRESENTATIVE_CASE_EXPANSION.md (F1) and
          stats/EXPANDED_CASE_NOTES.md (F2) @ RCL.sourceCommit. The 6 N1 anchors
          are already-covered (kept in the transmission walkthrough, not
          rewritten here); the 9 new cases have expanded F2 notes. */}
      <Card className="mb-3 overflow-hidden border-border/50 bg-surface-container-low">
        <CardHeader className="gap-1 border-b border-border/40 bg-surface-container-highest/50">
          <Kicker>Representative cases · walkthrough library</Kicker>
          <h2 className="font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface">
            Representative case library
          </h2>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-3 text-[12.5px] leading-relaxed text-on-surface/85">
          <p className="text-on-surface-variant/80">
            {`${RCL.totals.total} illustrative cases across ${RCL.totals.familiesTotal} mechanism families: `}
            {`${RCL.totals.anchors} already-covered N1 anchors + ${RCL.totals.newNotes} newly proposed F1/F2 cases. `}
            {`Representative cases are for walkthrough depth, not family-level inference.`}
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
            {`Restated ${AC.restatedOn} (AP3b): the live archive now holds ${AC.savedEvents} saved events; ` +
              `the accepted track-record corpus is ${AC.trackRecordTotal} ` +
              `(${AC.anySupporting} any-supporting / ${AC.contradicted} contradicted / ${AC.unresolved} unresolved) ` +
              `and the coverage / analysis denominator is ${AC.coverageDenominator}, after ` +
              `${AC.syntheticSeedFlagged} synthetic/test seed rows were flagged in event_hygiene and excluded ` +
              `(kept in the archive, never deleted). Phase 1 and Phase 2 remain separate pools.`}
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
