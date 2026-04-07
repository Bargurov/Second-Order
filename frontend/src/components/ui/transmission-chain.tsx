import { cn } from "@/lib/utils";
import { Landmark, Droplets, TrendingUp, Rocket } from "lucide-react";

const STEP_ICONS = [Landmark, Droplets, TrendingUp, Rocket];
const STEP_LABELS = ["Event", "Channel", "Market", "Outcome"];
const STEP_COLORS = [
  "text-primary",
  "text-secondary-dim",
  "text-secondary-dim",
  "text-primary",
];

// ---------------------------------------------------------------------------
// Full chain — horizontal connected nodes
// ---------------------------------------------------------------------------

export function TransmissionChain({ steps }: { steps: string[] }) {
  if (!steps || steps.length === 0) return null;

  return (
    <div className="relative">
      {/* Connector line */}
      <div className="absolute top-10 left-0 w-full h-px bg-gradient-to-r from-transparent via-outline-variant/40 to-transparent z-0" />

      <div className="flex justify-between items-start relative gap-4">
        {steps.map((step, i) => {
          const Icon = STEP_ICONS[i] ?? TrendingUp;
          const label = STEP_LABELS[i] ?? `Step ${i + 1}`;
          const color = STEP_COLORS[i] ?? "text-on-surface-variant";
          const isFirst = i === 0;
          const isLast = i === steps.length - 1;

          return (
            <div key={i} className="flex flex-col items-center gap-4 z-10 flex-1">
              <div className={cn(
                "w-20 h-20 rounded-full bg-surface-container-highest border-4 border-surface-container-low flex items-center justify-center shadow-2xl",
                (isFirst || isLast) && "outline outline-1 outline-primary/30",
              )}>
                <Icon className={cn("h-7 w-7", color)} />
              </div>
              <div className="text-center max-w-[220px]">
                <p className={cn("text-[10px] font-bold uppercase tracking-widest mb-1.5", color)}>
                  {label}
                </p>
                <p className="text-[13px] text-on-surface leading-relaxed">
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
// Compact chain — horizontal for Market Mover cards
// ---------------------------------------------------------------------------

export function TransmissionChainCompact({ steps }: { steps: string[] }) {
  if (!steps || steps.length === 0) return null;
  const visible = steps.slice(0, 3);
  return (
    <div className="flex items-center gap-1 text-[10px] text-on-surface-variant overflow-hidden">
      {visible.map((step, i) => {
        const label = STEP_LABELS[i];
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
