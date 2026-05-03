import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

const MIDDLE_LABELS = ["Channel", "Mechanism", "Market"];

/** Returns the semantic label for a step at the given index in a chain of `total` steps. */
export function getStepLabel(index: number, total: number): string {
  if (index === 0) return "Trigger";
  if (index === total - 1) return "Impact";
  return MIDDLE_LABELS[index - 1] ?? "Channel";
}

/** Returns true if the step should use the accent (teal) dot color. */
export function isAccentStep(index: number, total: number): boolean {
  return index === 0 || index === total - 1;
}

// ---------------------------------------------------------------------------
// Full chain — vertical step ladder
// ---------------------------------------------------------------------------

export function TransmissionChain({ steps }: { steps: string[] }) {
  if (!steps || steps.length === 0) return null;

  return (
    <div className="flex flex-col">
      {steps.map((step, i) => {
        const isLast = i === steps.length - 1;
        const accent = isAccentStep(i, steps.length);
        const label = getStepLabel(i, steps.length);

        return (
          <div key={i} className="flex items-start gap-3">
            {/* Left column: dot + connector line */}
            <div className="flex flex-col items-center w-4 flex-shrink-0">
              <span
                className={cn(
                  "w-2 h-2 rounded-full border flex-shrink-0 mt-[3px]",
                  accent
                    ? "bg-primary/20 border-primary/60"
                    : "bg-surface-container border-outline-variant/50",
                )}
              />
              {!isLast && (
                <span className="w-px flex-1 min-h-[14px] bg-outline-variant/30 mt-1" />
              )}
            </div>
            {/* Right column: label + step text */}
            <div className={cn("pb-3", isLast && "pb-0")}>
              <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-primary/40 mb-0.5">
                {label}
              </p>
              <p className="text-[12px] text-on-surface leading-snug">{step}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Circular chain — horizontal nodes connected by a faint line.
// Same data contract as TransmissionChain (string[] steps).  Use on the
// Event Detail surface where the chain is visually primary; the vertical
// ladder still serves callers that need a dense, narrow column.
// ---------------------------------------------------------------------------

export function TransmissionChainCircular({ steps }: { steps: string[] }) {
  if (!steps || steps.length === 0) return null;

  return (
    <div className="relative">
      {/* Connector line — sits behind the nodes, pinned to node center */}
      <div
        aria-hidden
        className="absolute left-0 right-0 h-px bg-gradient-to-r from-transparent via-outline-variant/40 to-transparent"
        style={{ top: "2.5rem" }}
      />

      <div className="relative flex justify-between items-start gap-3">
        {steps.map((step, i) => {
          const accent = isAccentStep(i, steps.length);
          const label = getStepLabel(i, steps.length);
          return (
            <div
              key={i}
              className="flex flex-col items-center gap-3 z-10 flex-1 min-w-0"
            >
              <div
                className={cn(
                  "w-20 h-20 rounded-full bg-surface-container-highest flex items-center justify-center",
                  // 4px ring of the parent surface to "cut" the connector
                  "ring-4 ring-surface-container-low",
                  accent
                    ? "shadow-[0_0_0_1px_rgba(147,209,211,0.4)]"
                    : "shadow-[0_0_0_1px_rgba(71,70,86,0.5)]",
                )}
              >
                <span
                  className={cn(
                    "text-[11px] font-bold uppercase tracking-[0.18em]",
                    accent ? "text-primary" : "text-on-surface-variant/70",
                  )}
                >
                  {String(i + 1).padStart(2, "0")}
                </span>
              </div>
              <div className="text-center max-w-[160px]">
                <p
                  className={cn(
                    "text-[11px] font-bold uppercase tracking-[0.18em] mb-1",
                    accent ? "text-primary" : "text-on-surface-variant/55",
                  )}
                >
                  {label}
                </p>
                <p className="text-[12px] text-on-surface leading-snug">
                  {step}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compact chain — horizontal for Market Mover cards (unchanged)
// ---------------------------------------------------------------------------

const COMPACT_LABELS = ["Event", "Channel", "Market", "Outcome"];

export function TransmissionChainCompact({ steps }: { steps: string[] }) {
  if (!steps || steps.length === 0) return null;
  const visible = steps.slice(0, 3);
  return (
    <div className="flex items-center gap-1 text-[10px] text-on-surface-variant overflow-hidden">
      {visible.map((step, i) => {
        const label = COMPACT_LABELS[i];
        const truncated = step.length > 60 ? step.slice(0, 57) + "..." : step;
        return (
          <span key={i} className="flex items-center gap-1 min-w-0">
            {i > 0 && <span className="text-outline-variant shrink-0">&rarr;</span>}
            <span className="truncate">
              {label && <span className="font-bold uppercase tracking-wide text-[9px] text-on-surface-variant/60">{label}: </span>}
              {truncated}
            </span>
          </span>
        );
      })}
    </div>
  );
}
