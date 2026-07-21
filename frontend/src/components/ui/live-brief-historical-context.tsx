/**
 * live-brief-historical-context.tsx — the lazy, read-only historical-context
 * drawer for a Live Event Brief.
 *
 * Second Order's published historical evidence provides DESCRIPTIVE context for
 * a live event; it never classifies or forecasts it.  This drawer reuses the
 * existing tracked-only evidence surfaces unchanged — each published cohort's
 * card is mounted only when the operator opens it, so nothing is fetched on
 * load and the full dossier universe is never pulled automatically.  Where the
 * live family maps to no published cohort, the drawer says so and never infers
 * an analog.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import {
  HISTORICAL_CONTEXT_DISCLAIMER,
  NO_COMPARABLE_COHORT,
  type ComparableCohort,
} from "@/lib/live-brief/types";
import { MissionGEvidenceCard } from "@/components/ui/mission-g-evidence-card";
import { MissionIEvidenceCard } from "@/components/ui/mission-i-evidence-card";
import { MissionJEvidenceCard } from "@/components/ui/mission-j-evidence-card";
import { UniversalEventDossiersCard } from "@/components/ui/universal-event-dossiers";

export type HistoricalPanel = "mission-g" | "mission-i" | "mission-j" | "dossiers";

const PANEL_LABEL: Record<HistoricalPanel, string> = {
  "mission-g": "Mission G — mechanism context",
  "mission-i": "Mission I — ordinary-period context",
  "mission-j": "Mission J — robustness & transmission",
  dossiers: "Universal event dossiers",
};

/**
 * Which published cohorts are offered for a declared comparability.  FOMC maps
 * to all three aggregate records; OPEC maps to G and I (Mission J is the
 * hindsight-controlled FOMC program only); an undeclared / non-comparable
 * family maps to none — the complete dossier universe is still reachable as
 * general descriptive context, never as an inferred analog.
 */
export function availablePanels(cohort: ComparableCohort): HistoricalPanel[] {
  if (cohort === "FOMC") return ["mission-g", "mission-i", "mission-j", "dossiers"];
  if (cohort === "OPEC") return ["mission-g", "mission-i", "dossiers"];
  return ["dossiers"];
}

// ---------------------------------------------------------------------------
// Lazily-fetched cohort panels (each fetches only once mounted)
// ---------------------------------------------------------------------------

function MissionGPanel() {
  const { data, isError } = useQuery({
    queryKey: qk.missionGEvidence(),
    queryFn: () => api.missionGEvidence(),
    retry: false,
  });
  return <MissionGEvidenceCard data={data} unavailable={isError} />;
}

function MissionIPanel() {
  const { data, isError } = useQuery({
    queryKey: qk.missionIEvidence(),
    queryFn: () => api.missionIEvidence(),
    retry: false,
  });
  return <MissionIEvidenceCard data={data} unavailable={isError} />;
}

function MissionJPanel() {
  const { data, isError } = useQuery({
    queryKey: qk.missionJEvidence(),
    queryFn: () => api.missionJEvidence(),
    retry: false,
  });
  return <MissionJEvidenceCard data={data} unavailable={isError} />;
}

function DossiersPanel() {
  const { data, isError } = useQuery({
    queryKey: qk.eventDossierIndex(),
    queryFn: () => api.eventDossierIndex(),
    retry: false,
  });
  return <UniversalEventDossiersCard data={data} unavailable={isError} />;
}

function PanelBody({ panel }: { panel: HistoricalPanel }) {
  switch (panel) {
    case "mission-g":
      return <MissionGPanel />;
    case "mission-i":
      return <MissionIPanel />;
    case "mission-j":
      return <MissionJPanel />;
    case "dossiers":
      return <DossiersPanel />;
  }
}

// ---------------------------------------------------------------------------
// Drawer
// ---------------------------------------------------------------------------

export interface LiveBriefHistoricalContextProps {
  cohort: ComparableCohort;
  /** Documented static-render test seam; the live path opens via the buttons. */
  initialOpenPanel?: HistoricalPanel | null;
}

export function LiveBriefHistoricalContext({
  cohort,
  initialOpenPanel = null,
}: LiveBriefHistoricalContextProps) {
  const [open, setOpen] = useState<HistoricalPanel | null>(initialOpenPanel);
  const panels = availablePanels(cohort);

  return (
    <section aria-label="Historical research context" className="flex flex-col gap-3">
      <p className="text-xs italic leading-relaxed text-muted-foreground" data-testid="historical-disclaimer">
        {HISTORICAL_CONTEXT_DISCLAIMER}
      </p>

      {cohort === "NONE" ? (
        <p className="text-xs leading-relaxed text-foreground/80">
          {NO_COMPARABLE_COHORT} The complete published historical universe below is available as
          general descriptive context only.
        </p>
      ) : (
        <p className="text-xs leading-relaxed text-foreground/80">
          Declared comparable cohort: <span className="font-semibold">{cohort}</span>. Open a published
          record for descriptive context; nothing is fetched until you do.
        </p>
      )}

      <div role="group" aria-label="Published historical records" className="flex flex-wrap gap-2">
        {panels.map((p) => {
          const isOpen = open === p;
          return (
            <button
              key={p}
              type="button"
              aria-pressed={isOpen}
              aria-controls={`hist-panel-${p}`}
              onClick={() => setOpen(isOpen ? null : p)}
              className={[
                "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                isOpen
                  ? "border-primary/40 bg-primary/10 text-foreground"
                  : "border-border bg-secondary text-muted-foreground hover:text-foreground",
              ].join(" ")}
            >
              {isOpen ? "Close" : "Open"}: {PANEL_LABEL[p]}
            </button>
          );
        })}
      </div>

      {open && (
        <div id={`hist-panel-${open}`} className="rounded-lg border border-border bg-card/60 p-3" data-testid="historical-panel">
          <p className="mb-2 text-[11px] italic text-muted-foreground">{HISTORICAL_CONTEXT_DISCLAIMER}</p>
          <PanelBody panel={open} />
        </div>
      )}
    </section>
  );
}
