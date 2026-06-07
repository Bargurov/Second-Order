import { cn } from "@/lib/utils";
import {
  BarChart3,
  Newspaper,
  FlaskConical,
  Clock,
  Target,
  BookOpen,
  Library,
  LayoutGrid,
} from "lucide-react";
import type { Page } from "./sidebar";

// Tab order mirrors the Workspace > Context > Research grouping in the
// sidebar: Portfolio (default) leads, Headlines is the secondary
// supporting context, Analyze is the drill-in.  Market replaces the
// old "Overview" — the macro/uncertainty/headlines surface lives
// behind Context now, not at the root.
const TABS: { id: Page; label: string; icon: React.ElementType }[] = [
  { id: "market",    label: "Market",    icon: BarChart3 },
  { id: "portfolio", label: "Portfolio", icon: BookOpen },
  { id: "headlines", label: "Headlines", icon: Newspaper },
  { id: "analyze",   label: "Analyze",   icon: FlaskConical },
  { id: "cases",     label: "Case Library", icon: Library },
  { id: "events",    label: "Archive",   icon: Clock },
  { id: "backtest",  label: "Backtest",  icon: Target },
  { id: "demo",      label: "Section C Demo", icon: LayoutGrid },
];

interface BottomNavProps {
  current: Page;
  onNavigate: (page: Page) => void;
}

export function BottomNav({ current, onNavigate }: BottomNavProps) {
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-30 flex h-14 items-stretch border-t border-border/80 bg-background/95 backdrop-blur-sm md:hidden">
      {TABS.map(({ id, label, icon: Icon }) => {
        const active = current === id;
        return (
          <button
            key={id}
            onClick={() => onNavigate(id)}
            className={cn(
              "relative flex flex-1 flex-col items-center justify-center gap-1 py-2 transition-colors",
              active
                ? "text-primary"
                : "text-muted-foreground/55 hover:text-muted-foreground",
            )}
          >
            {/* Top accent bar — matches sidebar's proportional accent language */}
            {active && (
              <span className="absolute top-0 left-1/2 -translate-x-1/2 h-[2px] w-6 rounded-b-full bg-primary" />
            )}
            <Icon className={cn("h-[15px] w-[15px] shrink-0", active && "text-primary")} />
            <span
              className={cn(
                "text-[11px] font-semibold tracking-[0.04em] leading-none",
                active ? "text-primary" : "text-muted-foreground/70",
              )}
            >
              {label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
