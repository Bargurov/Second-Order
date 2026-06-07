import { useState, useCallback, useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sidebar, type Page } from "@/components/layout/sidebar";
import { TopBar } from "@/components/layout/top-bar";
import { BottomNav } from "@/components/layout/bottom-nav";
import { MarketOverview } from "@/components/pages/market-overview";
import { InboxWorkbench } from "@/components/pages/inbox-workbench";
import { AnalysisView } from "@/components/pages/analysis-view";
import { RecentEvents } from "@/components/pages/recent-events";
import { CaseLibrary } from "@/components/pages/case-library";
import { Backtest } from "@/components/pages/backtest";
import { PortfolioPage } from "@/components/pages/portfolio-page";
import { SectionCDemo } from "@/components/pages/section-c-demo";
import { ErrorBoundary } from "@/components/error-boundary";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function useAutoCollapse() {
  const [collapsed, setCollapsed] = useState(() => window.innerWidth < 768);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const handler = (e: MediaQueryListEvent) => setCollapsed(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return [collapsed, setCollapsed] as const;
}

export default function App() {
  // Default home page is Market Context — the macro / uncertainty /
  // headlines stack the sidebar leads Workspace with.  ``overview`` is
  // a legacy alias that still resolves to the same surface.
  const [page, setPage] = useState<Page>("market");
  const [collapsed, setCollapsed] = useAutoCollapse();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [pendingHeadline, setPendingHeadline] = useState<string | undefined>();
  const [pendingContext, setPendingContext] = useState<string | undefined>();
  const [pendingEventId, setPendingEventId] = useState<number | undefined>();
  const [failedHeadlines, setFailedHeadlines] = useState<Set<string>>(new Set());

  const handleAnalysisFailed = useCallback((headline: string) => {
    setFailedHeadlines((prev) => {
      const next = new Set(prev);
      next.add(headline);
      return next;
    });
  }, []);

  const handleAnalysisSucceeded = useCallback((headline: string) => {
    setFailedHeadlines((prev) => {
      if (!prev.has(headline)) return prev;
      const next = new Set(prev);
      next.delete(headline);
      return next;
    });
  }, []);

  const analyzeHeadline = useCallback(
    (headline: string, opts?: { eventId?: number; context?: string }) => {
      setPendingHeadline(headline);
      setPendingContext(opts?.context);
      setPendingEventId(opts?.eventId);
      setPage("analyze");
    },
    [],
  );

  const navigate = useCallback((p: Page) => {
    setPage(p);
    setMobileOpen(false);
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={0}>
        {/*
          Layout shell — page-level scrolling.
          ------------------------------------
          The shell intentionally has NO height cap and NO `overflow-hidden`,
          so the document body scrolls naturally as one continuous page.
          The sidebar stays visible via `position: sticky` (sticky works
          inside a flex parent that is itself unconstrained in height) and
          the TopBar stays visible the same way.  Pages no longer need
          their own `h-full + overflow-y-auto` wrappers.
        */}
        <div className="relative flex min-h-dvh bg-background">
          {mobileOpen && (
            <div
              className="fixed inset-0 z-40 bg-black/50 md:hidden"
              onClick={() => setMobileOpen(false)}
            />
          )}
          <div
            className={`
              ${mobileOpen ? "fixed inset-y-0 left-0 z-50" : "hidden"}
              md:sticky md:top-0 md:block md:h-dvh md:self-start md:shrink-0
            `}
          >
            <Sidebar
              current={page}
              onNavigate={navigate}
              collapsed={collapsed}
            />
          </div>
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="sticky top-0 z-30">
              <TopBar
                page={page}
                sidebarCollapsed={collapsed}
                onToggleSidebar={() => {
                  if (window.innerWidth < 768) {
                    setMobileOpen((o) => !o);
                  } else {
                    setCollapsed((c) => !c);
                  }
                }}
              />
            </div>
            <main className="relative flex-1 px-3 pb-16 pt-3 md:px-5 md:pb-5 md:pt-4">
              <div className="page-enter w-full" key={page}>
                {/* Per-page error boundary.  The outer ``key={page}`` on the
                    wrapper div remounts the subtree on navigation, so the
                    boundary resets automatically when the user moves to a
                    different page.  A crash inside one page therefore
                    cannot blank the surrounding shell or persist past the
                    next navigation. */}
                <ErrorBoundary scope="page">
                  {/* Market Context — the macro/uncertainty/headlines surface,
                      reached explicitly via the ``market`` route.  ``overview``
                      is a back-compat alias so older deep links and any
                      setPage("overview") callers still resolve to the same
                      page; preserve until callers migrate. */}
                  {(page === "market" || page === "overview") && (
                    <MarketOverview onAnalyze={analyzeHeadline} failedHeadlines={failedHeadlines} onOpenHeadlines={() => navigate("headlines")} />
                  )}
                  {page === "headlines" && (
                    <InboxWorkbench onAnalyze={analyzeHeadline} failedHeadlines={failedHeadlines} />
                  )}
                  {page === "analyze" && (
                    <AnalysisView
                      initialHeadline={pendingHeadline}
                      initialContext={pendingContext}
                      initialEventId={pendingEventId}
                      onHeadlineConsumed={() => {
                        setPendingHeadline(undefined);
                        setPendingContext(undefined);
                        setPendingEventId(undefined);
                      }}
                      // Back navigates to the default workspace landing.
                      onBack={() => setPage("market")}
                      onAnalysisFailed={handleAnalysisFailed}
                      onAnalysisSucceeded={handleAnalysisSucceeded}
                    />
                  )}
                  {page === "events" && <RecentEvents />}
                  {page === "cases" && <CaseLibrary />}
                  {page === "backtest" && <Backtest />}
                  {page === "portfolio" && <PortfolioPage onAnalyze={analyzeHeadline} />}
                  {page === "demo" && <SectionCDemo />}
                </ErrorBoundary>
              </div>
            </main>
          </div>
          <BottomNav current={page} onNavigate={navigate} />
        </div>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
