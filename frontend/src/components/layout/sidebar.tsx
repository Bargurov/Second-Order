import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  BarChart3,
  Newspaper,
  FlaskConical,
  Clock,
  Target,
  BookOpen,
  Library,
  ClipboardList,
  LayoutGrid,
  NotebookPen,
  Zap,
} from "lucide-react";

/** Page identifiers.  ``"overview"`` is retained as a back-compat alias
 *  for the Market Context surface — App.tsx routes both ``overview`` and
 *  ``market`` to ``<MarketOverview>`` so older deep links and any
 *  ``setPage("overview")`` callers still resolve.  ``"market"`` is the
 *  current default workspace landing. */
export type Page = "overview" | "market" | "headlines" | "analyze" | "events" | "backtest" | "cases" | "evidence" | "portfolio" | "brief" | "demo";

type NavItem = { id: Page; label: string; icon: React.ElementType };
type NavGroup = { group: string; items: NavItem[] };

// Workspace leads with Market context (the new default landing), then
// Portfolio, Headlines, and Analyze.  Research holds the historical /
// validation surfaces — Archive and Backtest.  The previous "Context"
// group was folded into Workspace so the daily reading flow lives in a
// single primary nav cluster.  Section C Demo (and the design package's
// Thesis Module) are reference / demo surfaces only: they are kept OUT of
// the primary nav groups so the app does not read as a demo.  Section C
// Demo stays reachable via the demoted reference link below the nav
// (rendered in the sidebar footer), and its App.tsx route is unchanged.
const NAV_GROUPS: NavGroup[] = [
  {
    group: "Workspace",
    items: [
      { id: "brief",     label: "Live Brief", icon: NotebookPen },
      { id: "market",    label: "Market", icon: BarChart3 },
      { id: "portfolio", label: "Portfolio",      icon: BookOpen },
      { id: "headlines", label: "Headlines",      icon: Newspaper },
      { id: "analyze",   label: "Analyze",        icon: FlaskConical },
    ],
  },
  {
    group: "Research",
    items: [
      { id: "cases",    label: "Case Library",     icon: Library },
      { id: "evidence", label: "Evidence Overview", icon: ClipboardList },
      { id: "events",   label: "Archive",          icon: Clock },
      { id: "backtest", label: "Backtest",         icon: Target },
    ],
  },
];

interface SidebarProps {
  current: Page;
  onNavigate: (page: Page) => void;
  collapsed?: boolean;
}

export function Sidebar({ current, onNavigate, collapsed = false }: SidebarProps) {
  return (
    <aside
      className={cn(
        "flex h-full shrink-0 flex-col bg-sidebar text-sidebar-foreground transition-[width] duration-200",
        "border-r border-sidebar-border/60",
        collapsed ? "w-14" : "w-[232px]",
      )}
    >
      {/* Brand */}
      <div
        className={cn(
          collapsed
            ? "flex h-14 items-center justify-center"
            : "flex h-14 items-center gap-2.5 px-4",
        )}
      >
        <div
          className={cn(
            "flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-md",
            "bg-[radial-gradient(120%_120%_at_20%_20%,#2a4f50_0%,#0d1f20_55%,#06111a_100%)]",
            "shadow-[inset_0_0_0_1px_rgba(147,209,211,0.22)]",
            "text-primary",
          )}
        >
          <Zap className="h-3 w-3" />
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <p className="font-headline truncate text-[13px] font-bold leading-none tracking-[-0.01em] text-on-surface">
              Second Order
            </p>
            <p className="mt-1 truncate text-[10px] uppercase tracking-[0.12em] text-on-surface-variant/70">
              Market Forensics
            </p>
          </div>
        )}
      </div>

      {/* Navigation */}
      <ScrollArea className="flex-1 px-2 py-3">
        <nav className="flex flex-col gap-5">
          {NAV_GROUPS.map((group) => (
            <div key={group.group} className="flex flex-col">
              {!collapsed && (
                <div className="mb-1.5 px-2.5 text-[10px] font-medium uppercase tracking-[0.14em] text-on-surface-variant/60">
                  {group.group}
                </div>
              )}
              {group.items.map(({ id, label, icon: Icon }) => {
                const isActive = current === id;

                const btn = (
                  <Button
                    key={id}
                    variant="ghost"
                    size="sm"
                    className={cn(
                      "h-8 w-full justify-start gap-2.5 rounded-md px-2.5 text-[13px] font-medium",
                      collapsed && "justify-center px-0",
                      isActive
                        ? "bg-primary/[0.09] text-on-surface hover:bg-primary/[0.12]"
                        : "text-on-surface-variant/85 hover:bg-white/[0.025] hover:text-on-surface font-medium",
                    )}
                    onClick={() => onNavigate(id)}
                  >
                    <Icon
                      className={cn(
                        "h-3.5 w-3.5 shrink-0",
                        isActive ? "text-primary" : "text-on-surface-variant/55",
                      )}
                    />
                    {!collapsed && <span className="truncate">{label}</span>}
                  </Button>
                );

                if (collapsed) {
                  return (
                    <Tooltip key={id}>
                      <TooltipTrigger asChild>{btn}</TooltipTrigger>
                      <TooltipContent side="right">{label}</TooltipContent>
                    </Tooltip>
                  );
                }
                return btn;
              })}
            </div>
          ))}
        </nav>
      </ScrollArea>

      {/* Reference link — Section C Demo is an artifact-backed demo surface,
          demoted out of the primary nav groups above and kept reachable here
          as a quiet, de-emphasized reference link (label unchanged). */}
      <div className="px-2 pb-1 pt-1.5 border-t border-sidebar-border/40">
        {collapsed ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className={cn(
                  "h-7 w-full justify-center rounded-md px-0 text-[12px]",
                  current === "demo"
                    ? "bg-primary/[0.09] text-on-surface"
                    : "text-on-surface-variant/55 hover:bg-white/[0.025] hover:text-on-surface-variant/85",
                )}
                onClick={() => onNavigate("demo")}
              >
                <LayoutGrid
                  className={cn(
                    "h-3.5 w-3.5 shrink-0",
                    current === "demo" ? "text-primary" : "text-on-surface-variant/45",
                  )}
                />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">Section C Demo</TooltipContent>
          </Tooltip>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            className={cn(
              "h-7 w-full justify-start gap-2.5 rounded-md px-2.5 text-[12px] font-medium",
              current === "demo"
                ? "bg-primary/[0.09] text-on-surface hover:bg-primary/[0.12]"
                : "text-on-surface-variant/55 hover:bg-white/[0.025] hover:text-on-surface-variant/85",
            )}
            onClick={() => onNavigate("demo")}
          >
            <LayoutGrid
              className={cn(
                "h-3.5 w-3.5 shrink-0",
                current === "demo" ? "text-primary" : "text-on-surface-variant/45",
              )}
            />
            <span className="truncate">Section C Demo</span>
          </Button>
        )}
      </div>

      {/* Footer */}
      <div
        className={cn(
          collapsed
            ? "flex h-10 items-center justify-center"
            : "flex h-10 items-center gap-2 px-4",
        )}
      >
        {!collapsed ? (
          <>
            <span
              className="h-1.5 w-1.5 rounded-full bg-primary shadow-[0_0_8px_rgba(147,209,211,0.6)]"
              aria-hidden
            />
            <span className="text-[10.5px] text-on-surface-variant/60">Research</span>
            <span className="ml-auto font-num text-[10px] tabular-nums text-on-surface-variant/45">
              v0.1.0
            </span>
          </>
        ) : (
          <span className="h-1.5 w-1.5 rounded-full bg-primary shadow-[0_0_6px_rgba(147,209,211,0.55)]" />
        )}
      </div>
    </aside>
  );
}
