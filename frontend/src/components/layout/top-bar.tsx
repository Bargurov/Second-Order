import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  PanelLeftClose,
  PanelLeft,
  BarChart3,
  Newspaper,
  FlaskConical,
  Clock,
  Target,
} from "lucide-react";
import { api } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import type { Page } from "./sidebar";

const PAGE_META: Record<Page, { title: string; icon: React.ElementType }> = {
  overview:  { title: "Market Overview",  icon: BarChart3 },
  headlines: { title: "Headlines",        icon: Newspaper },
  analyze:   { title: "Analysis",         icon: FlaskConical },
  events:    { title: "Research Archive",  icon: Clock },
  backtest:  { title: "Backtest",          icon: Target },
};

interface TopBarProps {
  page: Page;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
}

export function TopBar({ page, sidebarCollapsed, onToggleSidebar }: TopBarProps) {
  const meta = PAGE_META[page];
  const Icon = meta.icon;
  const isOverview = page === "overview";

  const { isSuccess, isError } = useQuery({
    queryKey: qk.health(),
    queryFn: () => api.health(),
    refetchInterval: 30_000,
    retry: false,
  });
  const apiOk = isSuccess ? true : isError ? false : null;

  return (
    <header className={cn(
      "flex h-14 shrink-0 items-center gap-3 px-4 md:px-5",
      isOverview
        ? "bg-surface-container-low"
        : "border-b border-border/80 bg-background/90 backdrop-blur-sm",
    )}>
      <Button
        variant="ghost"
        size="icon"
        className="h-8 w-8 rounded-xl"
        onClick={onToggleSidebar}
        aria-label="Toggle sidebar"
      >
        {sidebarCollapsed ? (
          <PanelLeft className="h-3.5 w-3.5" />
        ) : (
          <PanelLeftClose className="h-3.5 w-3.5" />
        )}
      </Button>

      {!isOverview && (
        <>
          <div className="h-5 w-px bg-border" />
          <div className="flex min-w-0 items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-border/80 bg-surface-container shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            </div>
            <div className="min-w-0">
              <p className="section-kicker">Workspace</p>
              <h1 className="truncate text-sm font-semibold tracking-[-0.01em]">{meta.title}</h1>
            </div>
          </div>
        </>
      )}

      <div className={cn(
        "ml-auto hidden items-center gap-2 text-2xs text-on-surface-variant",
        "sm:flex",
      )}>
        <span className="metric-chip">
          <span className={cn(
            "h-1.5 w-1.5 rounded-full",
            apiOk === true && "bg-primary",
            apiOk === false && "bg-error",
            apiOk === null && "bg-border",
          )} />
          {apiOk === true ? "API live" : apiOk === false ? "API offline" : "API checking"}
        </span>
      </div>
    </header>
  );
}
