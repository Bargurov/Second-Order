import { useState, useCallback, useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sidebar, type Page } from "@/components/layout/sidebar";
import { TopBar } from "@/components/layout/top-bar";
import { MarketOverview } from "@/components/pages/market-overview";
import { HeadlinesPage } from "@/components/pages/headlines-page";
import { AnalysisView } from "@/components/pages/analysis-view";
import { RecentEvents } from "@/components/pages/recent-events";
import { Backtest } from "@/components/pages/backtest";

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
  const [page, setPage] = useState<Page>("overview");
  const [collapsed, setCollapsed] = useAutoCollapse();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [pendingHeadline, setPendingHeadline] = useState<string | undefined>();
  const [pendingContext, setPendingContext] = useState<string | undefined>();
  const [pendingEventId, setPendingEventId] = useState<number | undefined>();

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
            <main className="relative flex-1 px-3 pb-3 pt-3 md:px-5 md:pb-5 md:pt-4">
              <div className="page-enter w-full" key={page}>
                {page === "overview" && <MarketOverview onAnalyze={analyzeHeadline} />}
                {page === "headlines" && (
                  <HeadlinesPage onAnalyze={analyzeHeadline} />
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
                    onBack={() => setPage("overview")}
                  />
                )}
                {page === "events" && <RecentEvents />}
                {page === "backtest" && <Backtest />}
              </div>
            </main>
          </div>
        </div>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
