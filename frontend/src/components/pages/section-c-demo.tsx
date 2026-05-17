import { useQuery } from "@tanstack/react-query";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  getDemoDailyMarket,
  getDemoEvidenceSummary,
  getDemoStillMovingMarket,
  getDemoWeeklyMarket,
} from "@/lib/api";

import { DailyMarketPanel } from "@/components/demo/daily-market-panel";
import {
  EvidenceSummaryPanel,
  type EvidenceSummaryResponse,
} from "@/components/demo/evidence-summary-panel";
import { StillMovingMarketPanel } from "@/components/demo/still-moving-market-panel";
import { WeeklyMarketPanel } from "@/components/demo/weekly-market-panel";

/**
 * Section C Demo page.
 *
 * Hosts four artifact-backed demo panels:
 *   1. Daily Market           — GET /demo/daily-market
 *   2. Weekly Market          — GET /demo/weekly-market
 *   3. Still Moving Market    — GET /demo/still-moving-market
 *   4. Evidence Summary       — GET /demo/evidence-summary
 *
 * Each panel fetches independently so one failing endpoint does not
 * hide the others.  Empty / no-item states are owned by the panel
 * components; this page only renders the loading skeleton and a
 * non-blocking error notice when a fetch fails.
 *
 * Conservative language:
 *   * No claim of "validation", "proof", "alpha", or causality.
 *   * The page describes record counts and artifact provenance only.
 *   * Raw-p and FDR-significant counts are surfaced as separate
 *     fields by the Evidence Summary panel; this shell does not
 *     reframe one as the other.
 */

const FETCH_STALE_MS = 60_000;

// ---------------------------------------------------------------------------
// Panel wrapper — keeps the kicker/title/description chrome from the
// original shell so the section reads as four cards in a grid.
// ---------------------------------------------------------------------------

interface PanelCardProps {
  kicker:   string;
  title:    string;
  blurb:    string;
  children: React.ReactNode;
}

function PanelCard({ kicker, title, blurb, children }: PanelCardProps) {
  return (
    <Card className="bg-card">
      <CardHeader>
        <p className="section-kicker">{kicker}</p>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{blurb}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function PanelSkeleton() {
  return (
    <div className="space-y-2" aria-label="Loading">
      <Skeleton className="h-16 w-full rounded-md" />
      <Skeleton className="h-16 w-full rounded-md" />
    </div>
  );
}

function PanelErrorNotice({ error }: { error: unknown }) {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : "Could not load this panel.";
  return (
    <div
      role="alert"
      className="rounded-md border border-dashed border-border/70 bg-muted/30 p-3"
    >
      <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground/80">
        Unavailable
      </p>
      <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
        {message}
      </p>
      <p className="mt-1 text-[11px] leading-5 text-muted-foreground/70">
        Other panels are unaffected.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function SectionCDemo() {
  const dailyQuery = useQuery({
    queryKey: ["demo", "daily-market"] as const,
    queryFn:  () => getDemoDailyMarket(),
    staleTime: FETCH_STALE_MS,
  });

  const weeklyQuery = useQuery({
    queryKey: ["demo", "weekly-market"] as const,
    queryFn:  () => getDemoWeeklyMarket(),
    staleTime: FETCH_STALE_MS,
  });

  const stillMovingQuery = useQuery({
    queryKey: ["demo", "still-moving-market"] as const,
    queryFn:  () => getDemoStillMovingMarket(),
    staleTime: FETCH_STALE_MS,
  });

  const evidenceQuery = useQuery({
    queryKey: ["demo", "evidence-summary"] as const,
    queryFn:  () => getDemoEvidenceSummary(),
    staleTime: FETCH_STALE_MS,
  });

  // Map the API's PersistenceSignal object to the string label the
  // still-moving panel expects.  When the source carried no signal,
  // the API returns null and the panel renders without the pill.
  const stillMovingItems =
    stillMovingQuery.data?.items.map((item) => ({
      ...item,
      persistence_signal: item.persistence_signal?.label ?? null,
    })) ?? [];

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <p className="section-kicker">Section C Demo</p>
        <h1 className="font-headline text-xl font-semibold leading-tight tracking-[-0.01em] text-foreground">
          Section C Demo
        </h1>
        <p className="text-sm leading-6 text-muted-foreground">
          Artifact-backed market headlines and conservative evidence summary.
        </p>
        <p className="text-xs leading-5 text-muted-foreground/80">
          Every panel below reads from a reviewed artifact on disk.
          Record counts and verdict tallies are surfaced as the
          artifact records them — raw-p candidates are never reframed
          as FDR-significant. Nothing on this page constitutes a
          forecast or a trade signal.
        </p>
      </header>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <PanelCard
          kicker="Daily"
          title="Daily Market"
          blurb="Artifact-backed Daily items read from reviewed analyzed_event_artifact files."
        >
          {dailyQuery.isPending ? (
            <PanelSkeleton />
          ) : dailyQuery.isError ? (
            <PanelErrorNotice error={dailyQuery.error} />
          ) : (
            <DailyMarketPanel items={dailyQuery.data.items} />
          )}
        </PanelCard>

        <PanelCard
          kicker="Weekly"
          title="Weekly Market"
          blurb="Weekly mover items collapsed by the canonicalization helper."
        >
          {weeklyQuery.isPending ? (
            <PanelSkeleton />
          ) : weeklyQuery.isError ? (
            <PanelErrorNotice error={weeklyQuery.error} />
          ) : (
            <WeeklyMarketPanel items={weeklyQuery.data.items} />
          )}
        </PanelCard>

        <PanelCard
          kicker="Still Moving"
          title="Still Moving Market"
          blurb="Persistent candidates that pass the strict Still Moving gate."
        >
          {stillMovingQuery.isPending ? (
            <PanelSkeleton />
          ) : stillMovingQuery.isError ? (
            <PanelErrorNotice error={stillMovingQuery.error} />
          ) : (
            <StillMovingMarketPanel items={stillMovingItems} />
          )}
        </PanelCard>

        <PanelCard
          kicker="Evidence"
          title="Evidence Summary"
          blurb="Cohort summary and verdict tallies from the freeze-candidate evidence artifact."
        >
          {evidenceQuery.isPending ? (
            <PanelSkeleton />
          ) : evidenceQuery.isError ? (
            <PanelErrorNotice error={evidenceQuery.error} />
          ) : (
            <EvidenceSummaryPanel
              data={evidenceQuery.data as unknown as EvidenceSummaryResponse}
            />
          )}
        </PanelCard>
      </section>
    </div>
  );
}
