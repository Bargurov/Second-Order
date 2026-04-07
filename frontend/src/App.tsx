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
import { cn } from "@/lib/utils";

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

  const analyzeHeadline = useCallback((headline: string, context?: string) => {
    setPendingHeadline(headline);
    setPendingContext(context);
    setPage("analyze");
  }, []);

  const navigate = useCallback((p: Page) => {
    setPage(p);
    setMobileOpen(false);
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={0}>
        <div className="flex h-dvh overflow-hidden bg-background">
          {mobileOpen && (
            <div
              className="fixed inset-0 z-40 bg-black/50 md:hidden"
              onClick={() => setMobileOpen(false)}
            />
          )}
          <div className={`
            ${mobileOpen ? "fixed inset-y-0 left-0 z-50" : "hidden"}
            md:relative md:block
          `}>
            <Sidebar
              current={page}
              onNavigate={navigate}
              collapsed={collapsed}
            />
          </div>
          <div className="flex min-w-0 flex-1 flex-col">
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
            <main className="relative flex-1 overflow-auto px-3 pb-3 pt-3 md:px-5 md:pb-5 md:pt-4">
              <div className={cn("mx-auto max-w-[1480px] page-enter", page === "overview" ? "h-full" : "min-h-full")} key={page}>
                {page === "overview" && <MarketOverview onAnalyze={analyzeHeadline} />}
                {page === "headlines" && (
                  <HeadlinesPage onAnalyze={analyzeHeadline} />
                )}
                {page === "analyze" && (
                  <AnalysisView
                    initialHeadline={pendingHeadline}
                    initialContext={pendingContext}
                    onHeadlineConsumed={() => { setPendingHeadline(undefined); setPendingContext(undefined); }}
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
