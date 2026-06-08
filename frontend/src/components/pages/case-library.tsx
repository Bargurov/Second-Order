/**
 * Case Library (R6B) — a guided, honest entry point.
 *
 * Fifteen real representative archived events that show the RANGE of outcomes —
 * strong support, contradiction, unresolved, data-limited, mechanism-rich (only
 * three any-supporting, the rest contradictions or unresolved/data-limited) —
 * without implying cherry-picked proof.  Each card links into
 * the existing EventDossier surface via the URL-addressable /share/:id route
 * (chosen over an in-app Archive deep-link, which would need a fetch-by-id path
 * since Archive resolves the detail only from its currently-loaded page).
 *
 * Pure / presentational: it renders the editorial `CURATED_CASES` registry plus
 * the standing denominator + non-claim copy.  It adds NO new analytics and no
 * new claims; live returns / event-study / scored outcome are read by the
 * dossier surface each card links to.
 */
import { ArrowUpRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CURATED_CASES, type CaseRole, type CuratedCase } from "@/lib/curated-cases";

// Muted, institutional role accents — teal for support, coral for the
// contradiction, slate for the unresolved / data-limited reads.
const ROLE_ACCENT: Record<CaseRole, string> = {
  "strong-support": "border-primary/30 bg-primary/[0.07] text-primary",
  contradiction: "border-[#ee7d77]/30 bg-[#ee7d77]/[0.07] text-[#ee7d77]",
  unresolved: "border-border bg-surface-container text-on-surface-variant",
  "data-limited": "border-border bg-surface-container text-on-surface-variant",
  "mechanism-rich": "border-primary/25 bg-primary/[0.05] text-primary/85",
};

const NON_CLAIMS = [
  "Representative cases — selected to show the range of outcomes, not a best-of.",
  "Each case is a descriptive event-window read at n = 1, not benchmark-adjusted significance.",
  "Not exhaustive; denominators differ by gate and data availability.",
  "Separate from the closed Phase 1 / Phase 2 FDR pools; no pooled denominator is implied.",
  "Illustrative reads, not a validation pool — only 3/15 are any-supporting, and representative cases do not replace the corpus-level denominators above.",
];

function Labelled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-on-surface-variant/55">{label}</p>
      <p className="mt-0.5 text-[12.5px] leading-relaxed text-on-surface/85">{children}</p>
    </div>
  );
}

function CaseCard({ c, onOpenCase }: { c: CuratedCase; onOpenCase?: (eventId: number) => void }) {
  return (
    <Card className="overflow-hidden border-border/50 bg-surface-container-low">
      <CardHeader className="gap-2 border-b border-border/40 bg-surface-container-highest/50">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em]",
              ROLE_ACCENT[c.role],
            )}
          >
            {c.roleLabel}
          </span>
          <span className="font-mono text-[10px] tabular-nums text-on-surface-variant/45">#{c.eventId}</span>
          {/* Deterministic mechanism family (family_inference), not a typed extraction. */}
          <span className="rounded border border-border/60 bg-surface-container px-1.5 py-0.5 font-mono text-[9.5px] text-on-surface-variant/70">
            {c.family}
          </span>
          {/* Event-study availability cue (W1A) — coral when unavailable. */}
          <span
            className={cn(
              "rounded border px-1.5 py-0.5 font-mono text-[9.5px]",
              c.eventStudyAvailable
                ? "border-border/60 bg-surface-container text-on-surface-variant/70"
                : "border-[#ee7d77]/30 bg-[#ee7d77]/[0.07] text-[#ee7d77]",
            )}
          >
            event-study: {c.eventStudyAvailable ? "available" : "unavailable"}
          </span>
          {!c.rawReturnsAvailable && (
            <Badge variant="outline" className="ml-auto text-[9.5px] font-normal text-on-surface-variant/70">
              Event-study readout carries the read
            </Badge>
          )}
        </div>
        {/* Primary action — open the in-app Archive/Event Detail dossier (richer
            than /share: it renders the validation_status_v2 outcome). */}
        <button
          type="button"
          data-open-event-id={c.eventId}
          onClick={() => onOpenCase?.(c.eventId)}
          className="text-left font-headline text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface hover:text-primary"
        >
          {c.headline}
        </button>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 pt-3">
        {/* Compact research-read — what this case shows (W1A). */}
        <p className="text-[12px] font-medium leading-relaxed text-on-surface/90">{c.demonstrates}</p>
        <p className="text-[12.5px] leading-relaxed text-on-surface/80">{c.mechanism}</p>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Labelled label="Outcome">{c.outcome}</Labelled>
          <Labelled label="Event-study">{c.eventStudyNote}</Labelled>
          <Labelled label="Why selected">{c.whySelected}</Labelled>
          <Labelled label="What it does not prove">{c.doesNotProve}</Labelled>
        </div>

        <p className="border-t border-border/40 pt-2 text-[11px] italic leading-relaxed text-on-surface-variant/70">
          {c.caveat}
        </p>

        <div className="flex items-center gap-3">
          <button
            type="button"
            data-open-event-id={c.eventId}
            onClick={() => onOpenCase?.(c.eventId)}
            className="inline-flex w-fit items-center gap-1 text-[11.5px] font-medium text-primary hover:underline"
          >
            Open dossier
            <ArrowUpRight className="h-3 w-3" />
          </button>
          {/* Secondary — the shell-free /share view (may omit the scored
              outcome, which the card above already states). */}
          <a
            href={`/share/${c.eventId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10.5px] text-on-surface-variant/55 hover:text-on-surface-variant/85"
          >
            Share link
          </a>
        </div>
      </CardContent>
    </Card>
  );
}

export function CaseLibrary({ onOpenCase }: { onOpenCase?: (eventId: number) => void } = {}) {
  return (
    <div className="mx-auto w-full max-w-5xl">
      {/* Header */}
      <header className="mb-5">
        <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-on-surface-variant/55">Research</p>
        <h1 className="mt-1 font-headline text-[22px] font-bold leading-tight tracking-[-0.01em] text-on-surface">
          Case Library
        </h1>
        <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-on-surface-variant/85">
          A guided, fifteen-case walkthrough of representative real events spanning the range of
          outcomes and mechanisms. Only three of the fifteen are any-supporting; the rest are
          contradictions or unresolved / data-limited reads.
        </p>

        {/* Denominator anchor + corpus split + slate mix (anti-cherry-pick) */}
        <div className="mt-3 flex flex-col gap-1 rounded-md border border-border/50 bg-surface-container-low px-3.5 py-2.5">
          <p className="text-[12px] font-medium text-on-surface/85">
            15 representative cases drawn from 81 market-scored events of 166 saved.
          </p>
          <p className="font-mono text-[11px] tabular-nums text-on-surface-variant/75">
            19 any-supporting · 35 contradicted · 27 unresolved.
          </p>
          <p className="font-mono text-[11px] tabular-nums text-on-surface-variant/60">
            This slate: 3 any-supporting · 5 contradicted · 7 unresolved (incl. 1 data-limited, 1 mechanism-rich) · 5 of 15 oil/energy by theme.
          </p>
        </div>

        {/* Standing non-claims */}
        <ul className="mt-2.5 flex flex-col gap-1">
          {NON_CLAIMS.map((line) => (
            <li key={line} className="flex items-start gap-1.5 text-[11px] leading-relaxed text-on-surface-variant/65">
              <span className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-on-surface-variant/40" aria-hidden />
              {line}
            </li>
          ))}
        </ul>
      </header>

      {/* Case cards */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {CURATED_CASES.map((c) => (
          <CaseCard key={c.eventId} c={c} onOpenCase={onOpenCase} />
        ))}
      </div>
    </div>
  );
}
