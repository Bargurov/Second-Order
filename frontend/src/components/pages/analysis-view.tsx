import { useState, useEffect, useCallback, useRef } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Send,
  Loader2,
  ArrowLeft,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  ShieldCheck,
  ShieldAlert,
  Shield,
  Eye,
  ChevronDown,
  ClipboardCopy,
  Check,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { Sparkline } from "@/components/ui/sparkline";
import { TickerChart } from "@/components/ui/ticker-chart";
import { MacroStrip } from "@/components/ui/macro-strip";
import { api, type AnalyzeResponse, type Ticker } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Skeletons
// ---------------------------------------------------------------------------

function AnalysisSkeleton() {
  return (
    <div className="space-y-3 pb-4">
      <Card>
        <CardHeader className="space-y-2">
          <Skeleton className="h-4 w-4/5" />
          <div className="flex gap-1.5">
            <Skeleton className="h-4 w-16 rounded" />
            <Skeleton className="h-4 w-20 rounded" />
            <Skeleton className="h-4 w-28 rounded" />
          </div>
        </CardHeader>
      </Card>
      <div className="grid gap-3 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          {[1, 2].map((k) => (
            <Card key={k}>
              <CardHeader><Skeleton className="h-3 w-24" /></CardHeader>
              <CardContent className="space-y-1.5">
                <Skeleton className="h-3.5 w-full" />
                <Skeleton className="h-3.5 w-5/6" />
              </CardContent>
            </Card>
          ))}
        </div>
        <div className="space-y-3">
          {[1, 2].map((k) => (
            <Card key={k}>
              <CardHeader><Skeleton className="h-3 w-20" /></CardHeader>
              <CardContent className="space-y-1.5">
                <Skeleton className="h-3.5 w-3/4" />
                <Skeleton className="h-3.5 w-2/3" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
      <Separator />
      <div className="space-y-2">
        <Skeleton className="h-3 w-24" />
        <div className="flex gap-2 overflow-hidden">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-28 shrink-0 rounded-lg" />
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CONFIDENCE_META: Record<
  string,
  { icon: React.ElementType; color: string; label: string }
> = {
  high:   { icon: ShieldCheck, color: "val-pos",  label: "High" },
  medium: { icon: Shield,      color: "text-amber-400", label: "Medium" },
  low:    { icon: ShieldAlert, color: "val-neg",  label: "Low" },
};

function pct(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-2xs font-medium uppercase tracking-widest text-foreground/72">
      {children}
    </h3>
  );
}

function formatAnalysisMarkdown(r: AnalyzeResponse): string {
  const lines: string[] = [];
  lines.push(`# ${r.headline}`);
  lines.push("");
  lines.push(`**Stage:** ${r.stage}  **Persistence:** ${r.persistence}  **Confidence:** ${r.analysis.confidence}`);
  if (r.event_date) lines.push(`**Event date:** ${r.event_date}`);
  lines.push("");

  lines.push("## What Changed");
  lines.push(r.analysis.what_changed);
  lines.push("");

  lines.push("## Mechanism Summary");
  lines.push(r.analysis.mechanism_summary);
  lines.push("");

  if (r.analysis.transmission_chain && r.analysis.transmission_chain.length > 0) {
    lines.push("## Transmission Chain");
    r.analysis.transmission_chain.forEach((step, i) => lines.push(`${i + 1}. ${step}`));
    lines.push("");
  }

  if (r.analysis.beneficiaries.length > 0) {
    lines.push("## Beneficiaries");
    r.analysis.beneficiaries.forEach((b) => lines.push(`- ${b}`));
    lines.push("");
  }

  if (r.analysis.losers.length > 0) {
    lines.push("## Losers");
    r.analysis.losers.forEach((l) => lines.push(`- ${l}`));
    lines.push("");
  }

  if (r.analysis.assets_to_watch.length > 0) {
    lines.push(`**Assets to watch:** ${r.analysis.assets_to_watch.join(", ")}`);
    lines.push("");
  }

  if (r.market.tickers.length > 0) {
    lines.push("## Market Check");
    lines.push("");
    lines.push("| Symbol | Role | Dir | 5d | 20d |");
    lines.push("|--------|------|-----|------|------|");
    r.market.tickers.forEach((t) => {
      const r5 = t.return_5d != null ? `${t.return_5d >= 0 ? "+" : ""}${t.return_5d.toFixed(2)}%` : "\u2014";
      const r20 = t.return_20d != null ? `${t.return_20d >= 0 ? "+" : ""}${t.return_20d.toFixed(2)}%` : "\u2014";
      const dir = t.direction_tag ?? "\u2014";
      lines.push(`| ${t.symbol} | ${t.role} | ${dir} | ${r5} | ${r20} |`);
    });
    lines.push("");
  }

  if (r.market.note) {
    lines.push(`> ${r.market.note.split("\n")[0]}`);
    lines.push("");
  }

  lines.push(`---`);
  lines.push(`*Exported from Second Order*`);
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Ticker card
// ---------------------------------------------------------------------------

// Compact return value: "+2.50%" with colour
function RetVal({ v, className: cls }: { v: number | null | undefined; className?: string }) {
  return (
    <span className={cn(
      "font-num text-2xs",
      v != null && v > 0 && "val-pos",
      v != null && v < 0 && "val-neg",
      v == null && "text-muted-foreground",
      cls,
    )}>
      {pct(v)}
    </span>
  );
}

function isSupporting(t: Ticker): boolean {
  return t.direction_tag === "supporting" || (t.direction_tag?.startsWith("supports") ?? false);
}

function isContradicting(t: Ticker): boolean {
  return t.direction_tag === "contradicting" || (t.direction_tag?.startsWith("contradicts") ?? false);
}

function TickerCard({
  ticker,
  selected,
  onToggle,
}: {
  ticker: Ticker;
  selected: boolean;
  onToggle: () => void;
}) {
  const noData = ticker.label === "needs more evidence";

  if (noData) {
    return (
      <div className="shrink-0 flex items-center gap-1 rounded border border-border/20 bg-secondary/15 px-1.5 py-1 opacity-40">
        <span className="font-num text-[10px] text-muted-foreground">{ticker.symbol}</span>
      </div>
    );
  }

  const supports = isSupporting(ticker);
  const contradicts = isContradicting(ticker);
  const r5 = ticker.return_5d;

  return (
    <button
      onClick={onToggle}
      className={cn(
        "shrink-0 rounded-lg border text-left transition-colors",
        "border-border bg-card hover:border-border/80",
        selected && "border-sidebar-primary/50 bg-sidebar-primary/5",
      )}
    >
      <div className="px-2.5 py-1.5 min-w-[7.5rem]">
        {/* Row 1: verdict dot + symbol + role + sparkline */}
        <div className="flex items-center gap-1.5">
          <span className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full",
            supports && "bg-[#4ade80]",
            contradicts && "bg-[#f87171]",
            !supports && !contradicts && "bg-border",
          )} />
          <span className="font-num text-[13px] font-semibold">{ticker.symbol}</span>
          <Badge variant={ticker.role === "beneficiary" ? "secondary" : "outline"} className="shrink-0">
            {ticker.role === "beneficiary" ? "long" : "short"}
          </Badge>
          <Sparkline
            data={ticker.spark ?? []}
            width={40}
            height={14}
            direction={ticker.return_20d}
            className="ml-auto"
          />
        </div>
        {/* Row 2: headline 5d return prominently + 1d and 20d smaller */}
        <div className="mt-1 flex items-baseline gap-1.5">
          <span className={cn(
            "font-num text-[13px] font-medium",
            r5 != null && r5 > 0 && "val-pos",
            r5 != null && r5 < 0 && "val-neg",
            r5 == null && "text-muted-foreground",
          )}>
            {pct(r5)}
          </span>
          <span className="text-[10px] text-muted-foreground">5d</span>
          <span className="text-border">|</span>
          <RetVal v={ticker.return_1d} className="text-[10px]" />
          <RetVal v={ticker.return_20d} className="text-[10px]" />
          {ticker.volume_ratio != null && ticker.volume_ratio >= 1.25 && (
            <span className="font-num text-[10px] text-muted-foreground">
              {ticker.volume_ratio.toFixed(1)}x
            </span>
          )}
          <ChevronDown className={cn(
            "ml-auto h-2.5 w-2.5 shrink-0 text-muted-foreground transition-transform",
            selected && "rotate-180",
          )} />
        </div>
      </div>
    </button>
  );
}

function fmtMktCap(v: number | null): string {
  if (v == null) return "\u2014";
  if (v >= 1e12) return `$${(v / 1e12).toFixed(1)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toLocaleString()}`;
}

function fmtVol(v: number | null): string {
  if (v == null) return "\u2014";
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return String(v);
}

function TickerDetail({ ticker, eventDate }: { ticker: Ticker; eventDate?: string }) {
  const supports = isSupporting(ticker);
  const contradicts = isContradicting(ticker);
  const vol = ticker.volume_ratio;
  const volHigh = vol != null && vol >= 1.25;

  const { data: chartData, isLoading: chartLoading } = useQuery({
    queryKey: qk.tickerChart(ticker.symbol, eventDate ?? ""),
    queryFn: () => api.tickerChart(ticker.symbol, eventDate!),
    enabled: !!eventDate,
    staleTime: 600_000,
  });

  const { data: info, isLoading: infoLoading } = useQuery({
    queryKey: qk.tickerInfo(ticker.symbol),
    queryFn: () => api.tickerInfo(ticker.symbol),
    staleTime: 3_600_000,
  });

  const { data: headlines } = useQuery({
    queryKey: qk.tickerHeadlines(ticker.symbol),
    queryFn: () => api.tickerHeadlines(ticker.symbol),
    staleTime: 300_000,
  });

  const hasInfo = info && (info.name || info.sector || info.market_cap);
  const hasChart = chartData && chartData.length > 2 && eventDate;
  const hasHeadlines = headlines && headlines.length > 0;

  return (
    <div className="fade-in rounded-2xl border border-border bg-card shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      {/* Header row */}
      <div className="flex items-center gap-3 px-4 py-2.5">
        <span className={cn(
          "h-2 w-2 shrink-0 rounded-full",
          supports && "bg-[#15803d]",
          contradicts && "bg-[#b91c1c]",
          !supports && !contradicts && "bg-border",
        )} />
        <span className="font-num text-sm font-semibold">{ticker.symbol}</span>
        {info?.name && (
          <span className="truncate text-xs text-muted-foreground">{info.name}</span>
        )}
        <Badge variant={ticker.role === "beneficiary" ? "secondary" : "outline"}>
          {ticker.role === "beneficiary" ? "long" : "short"}
        </Badge>
        <span className="ml-auto text-2xs text-muted-foreground">{ticker.label}</span>
      </div>

      {/* Company info strip */}
      {infoLoading && (
        <div className="flex gap-3 border-t border-border px-4 py-1.5">
          <Skeleton className="h-3 w-16" /><Skeleton className="h-3 w-20" /><Skeleton className="h-3 w-14" />
        </div>
      )}
      {!infoLoading && hasInfo && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 border-t border-border px-4 py-1.5 text-[10px] text-muted-foreground">
          {info!.sector && <span>{info!.sector}</span>}
          {info!.industry && <span>· {info!.industry}</span>}
          {info!.market_cap && <span className="font-num">Mkt cap {fmtMktCap(info!.market_cap)}</span>}
          {info!.avg_volume && <span className="font-num">Avg vol {fmtVol(info!.avg_volume)}</span>}
        </div>
      )}
      {!infoLoading && !hasInfo && (
        <div className="border-t border-border px-4 py-1.5">
          <span className="text-[10px] text-muted-foreground/60">Company info unavailable</span>
        </div>
      )}

      {/* Event-anchored chart */}
      {chartLoading && eventDate && (
        <div className="border-t border-border px-4 py-3">
          <Skeleton className="h-[100px] w-full rounded-lg" />
        </div>
      )}
      {!chartLoading && hasChart && (
        <div className="border-t border-border px-3 py-2">
          <TickerChart
            data={chartData!}
            eventDate={eventDate!}
            width={440}
            height={100}
            className="w-full"
          />
        </div>
      )}
      {!chartLoading && !hasChart && eventDate && (
        <div className="border-t border-border px-4 py-2">
          <span className="text-[10px] text-muted-foreground/60">Price chart unavailable for this date range</span>
        </div>
      )}

      {/* Data strip */}
      <div className="flex border-t border-border">
        {([
          ["1d", ticker.return_1d],
          ["5d", ticker.return_5d],
          ["20d", ticker.return_20d],
        ] as const).map(([label, val]) => (
          <div key={label} className="flex-1 flex items-center justify-center gap-1 py-1.5 border-r border-border">
            <span className="text-[10px] text-muted-foreground">{label}</span>
            <span className={cn(
              "font-num text-2xs font-medium",
              val != null && val > 0 && "val-pos",
              val != null && val < 0 && "val-neg",
              val == null && "text-muted-foreground",
            )}>
              {pct(val)}
            </span>
          </div>
        ))}
        <div className="flex-1 flex items-center justify-center gap-1 py-1.5 border-r border-border">
          <span className="text-[10px] text-muted-foreground">Vol</span>
          <span className={cn("font-num text-2xs font-medium", volHigh && "text-foreground")}>
            {vol != null ? `${vol.toFixed(1)}x` : "\u2014"}
          </span>
        </div>
        {ticker.vs_xle_5d != null && (
          <div className="flex-1 flex items-center justify-center gap-1 py-1.5">
            <span className="text-[10px] text-muted-foreground">vs Bench</span>
            <RetVal v={ticker.vs_xle_5d} className="font-medium" />
          </div>
        )}
      </div>

      {/* Verdict */}
      <div className="px-4 py-1.5 border-t border-border">
        <p className="text-2xs text-muted-foreground">
          {supports && "Supports hypothesis \u2014 "}
          {contradicts && "Contradicts hypothesis \u2014 "}
          {!supports && !contradicts && "Inconclusive \u2014 "}
          {ticker.return_5d != null && ticker.return_5d > 0 ? "up" : ticker.return_5d != null && ticker.return_5d < 0 ? "down" : "flat"}{" "}
          <RetVal v={ticker.return_5d} /> over 5 days
          {volHigh && <>, elevated volume ({vol?.toFixed(1)}x avg)</>}
          {ticker.vs_xle_5d != null && (
            <>, <RetVal v={ticker.vs_xle_5d} /> relative to sector</>
          )}
        </p>
      </div>

      {/* Related headlines */}
      {hasHeadlines && (
        <div className="border-t border-border px-4 py-2 space-y-1">
          <span className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground">
            Related headlines
          </span>
          {headlines!.map((h, i) => (
            <div key={i} className="flex items-baseline gap-2 text-xs text-muted-foreground">
              <span className="shrink-0 font-num text-[10px]">
                {h.source_count > 1 ? `${h.source_count}src` : ""}
              </span>
              <span className="leading-snug">{h.headline}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MarketCards({ tickers, eventDate }: { tickers: Ticker[]; eventDate?: string }) {
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const selectedTicker = tickers.find((t) => t.symbol === selectedSymbol);

  if (tickers.length === 0) {
    return (
      <p className="py-2 text-center text-2xs text-muted-foreground">
        No market data returned.
      </p>
    );
  }

  const withData = tickers.filter((t) => t.label !== "needs more evidence");
  const noData = tickers.filter((t) => t.label === "needs more evidence");

  const withDir = tickers.filter((t) => t.direction_tag != null);
  const supportCount = withDir.filter((t) => isSupporting(t)).length;

  return (
    <div className="space-y-2">
      {/* Card row */}
      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {withData.map((t) => (
          <TickerCard
            key={t.symbol}
            ticker={t}
            selected={selectedSymbol === t.symbol}
            onToggle={() =>
              setSelectedSymbol((s) => (s === t.symbol ? null : t.symbol))
            }
          />
        ))}
        {noData.length > 0 && noData.map((t) => (
          <TickerCard key={t.symbol} ticker={t} selected={false} onToggle={() => {}} />
        ))}
      </div>

      {/* Detail panel */}
      {selectedTicker && selectedTicker.label !== "needs more evidence" && (
        <TickerDetail ticker={selectedTicker} eventDate={eventDate} />
      )}

      {/* Hypothesis summary */}
      {withDir.length > 0 && (
        <p className="text-2xs text-muted-foreground">
          Hypothesis support:{" "}
          <span className={cn("font-num font-medium",
            supportCount === withDir.length && "val-pos",
            supportCount === 0 && "val-neg",
          )}>
            {supportCount}/{withDir.length}
          </span>{" "}
          tickers in predicted direction
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface AnalysisViewProps {
  initialHeadline?: string;
  initialContext?: string;
  onHeadlineConsumed?: () => void;
  onBack?: () => void;
}

type Phase = "idle" | "classify" | "analysis" | "market" | "complete";

export function AnalysisView({
  initialHeadline,
  initialContext,
  onHeadlineConsumed,
  onBack,
}: AnalysisViewProps) {
  const [headline, setHeadline] = useState("");
  const [eventDate, setEventDate] = useState("");
  const contextRef = useRef<string | undefined>(initialContext);
  const eventDateRef = useRef(eventDate);
  eventDateRef.current = eventDate;
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const loading = phase !== "idle" && phase !== "complete";

  // Abort any in-flight stream on unmount
  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, []);

  const submit = useCallback(async (h?: string) => {
    const text = (h ?? headline).trim();
    if (!text) return;

    // Abort previous stream before starting a new one
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setHeadline(text);
    setPhase("classify");
    setError(null);
    setResult(null);

    let partial: Partial<AnalyzeResponse> = { headline: text };

    try {
      await api.analyzeStream(
        {
          headline: text,
          event_date: eventDateRef.current || undefined,
          event_context: contextRef.current || undefined,
        },
        (stage, data) => {
          if (controller.signal.aborted) return;
          if (stage === "classify") {
            partial = {
              ...partial,
              stage: data.stage as string,
              persistence: data.persistence as string,
            };
            setResult(partial as AnalyzeResponse);
            setPhase("analysis");
          } else if (stage === "analysis") {
            partial = {
              ...partial,
              analysis: data.analysis as AnalyzeResponse["analysis"],
              is_mock: data.is_mock as boolean,
            };
            setResult(partial as AnalyzeResponse);
            setPhase("market");
          } else if (stage === "complete") {
            setResult(data as unknown as AnalyzeResponse);
            setPhase("complete");
          }
        },
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setPhase((p) => (p === "complete" ? p : "complete"));
      }
    } catch (e) {
      if (controller.signal.aborted) return; // expected — don't show error
      setError(e instanceof Error ? e.message : "Unable to run analysis.");
      setPhase("idle");
    }
  }, [headline]);

  useEffect(() => {
    if (initialHeadline) {
      setHeadline(initialHeadline);
      contextRef.current = initialContext;
      onHeadlineConsumed?.();
      submit(initialHeadline);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialHeadline]);

  const conf = result?.analysis
    ? (CONFIDENCE_META[result.analysis.confidence] ?? { icon: ShieldAlert, color: "val-neg", label: "?" })
    : null;
  const ConfIcon = conf?.icon ?? Shield;

  return (
    <div className="flex h-full flex-col gap-3">
      {/* Back + input bar */}
      <Card className="soft-panel shrink-0 overflow-hidden border-border/70">
        <CardContent className="space-y-3 px-4 py-4">
          {onBack && (
            <Button variant="ghost" size="sm" onClick={onBack} className="-ml-1.5 w-fit">
              <ArrowLeft className="h-3 w-3" />
              Back to Inbox
            </Button>
          )}
          <div className="space-y-1">
            <p className="section-kicker">Analysis</p>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold tracking-[-0.02em] text-foreground">Event Research</h2>
              <span className="metric-chip">
                {loading ? "Streaming progress" : result ? "Latest result loaded" : "Ready for input"}
              </span>
            </div>
            <p className="max-w-3xl text-[12px] leading-5 text-foreground/80">
              Run a staged review that classifies the event, drafts the mechanism, and then overlays market and macro context.
            </p>
          </div>
          <div className="grid gap-2.5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <label className="space-y-1.5">
              <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-foreground/72">
                Headline
              </span>
              <input
                type="text"
                placeholder="Paste a geopolitical, macro, or policy headline..."
                value={headline}
                onChange={(e) => setHeadline(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
                className="min-w-0 w-full rounded-xl border border-input bg-background px-3 py-2.5 text-[13px] leading-5 text-foreground placeholder:text-foreground/45 focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </label>
            <div className="grid gap-2 sm:grid-cols-[9rem_auto]">
              <label className="space-y-1.5">
                <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-foreground/72">
                  Event date
                </span>
                <input
                  type="date"
                  value={eventDate}
                  onChange={(e) => setEventDate(e.target.value)}
                  className="w-full rounded-xl border border-input bg-background px-3 py-2.5 text-2xs font-num text-foreground [color-scheme:light] focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </label>
              <Button
                onClick={() => submit()}
                disabled={loading || !headline.trim()}
                className="h-auto rounded-xl px-4 py-2.5 disabled:bg-primary/35 disabled:text-primary-foreground/80"
              >
                {loading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Send className="h-3.5 w-3.5" />
                )}
                {loading ? "Running analysis" : "Run analysis"}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Error */}
      {error && (
        <Card className="shrink-0 border-destructive/30 bg-destructive/5">
          <CardContent className="flex items-start gap-3 py-4 text-destructive">
            <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white">
              <AlertTriangle className="h-4 w-4" />
            </div>
            <div className="space-y-1">
              <p className="text-[12px] font-medium">Analysis unavailable</p>
              <p className="min-w-0 break-words text-2xs leading-5 text-destructive/90">{error}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Empty state */}
      {phase === "idle" && !result && !error && (
        <Card className="empty-surface flex flex-1 items-center justify-center">
          <CardContent className="flex max-w-md flex-col items-center gap-3 py-12 text-center text-muted-foreground">
            <div className="flex h-14 w-14 items-center justify-center rounded-full border border-border bg-white">
              <Eye className="h-6 w-6 opacity-70" />
            </div>
            <div className="space-y-1.5">
              <p className="text-sm font-medium text-foreground">No active analysis</p>
              <p className="text-[12px] leading-5 text-foreground/72">
                Paste a headline or open a cluster from the inbox to start a staged event review.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Initial skeleton — only before any data arrives */}
      {phase === "classify" && !result && (
        <ScrollArea className="min-h-0 flex-1">
          <AnalysisSkeleton />
        </ScrollArea>
      )}

      {/* Progressive results — render what we have, skeleton the rest */}
      {result && (
        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-3 pb-4 pr-2">
            {/* Header — available after classify stage */}
            <Card className="fade-in overflow-hidden border-border bg-card">
              <CardHeader className="gap-3 border-b border-border bg-secondary/35">
                <p className="section-kicker">Research output</p>
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-[15px] font-semibold leading-6 text-foreground">
                    {result.headline}
                  </CardTitle>
                  {phase === "complete" && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="shrink-0 h-6 px-2 text-foreground/72 hover:text-foreground"
                      onClick={() => {
                        navigator.clipboard.writeText(formatAnalysisMarkdown(result)).then(() => {
                          setCopied(true);
                          setTimeout(() => setCopied(false), 2000);
                        });
                      }}
                    >
                      {copied ? (
                        <><Check className="h-3 w-3 val-pos" />Copied</>
                      ) : (
                        <><ClipboardCopy className="h-3 w-3" />Copy Markdown</>
                      )}
                    </Button>
                  )}
                </div>
                <CardDescription className="flex flex-wrap items-center gap-1.5 pt-0.5">
                  {result.stage && <Badge variant="outline">{result.stage}</Badge>}
                  {result.persistence && <Badge variant="outline">{result.persistence}</Badge>}
                  {result.is_mock && <Badge variant="destructive">mock</Badge>}
                  {result.analysis && !result.is_mock && conf && (
                    <Badge variant="secondary" className={cn("gap-1", conf.color)}>
                      <ConfIcon className="h-3 w-3" />
                      {conf.label}
                    </Badge>
                  )}
                  {result.event_date && (
                    <span className="font-num text-2xs text-foreground/76">
                      event date {result.event_date}
                    </span>
                  )}
                  {loading && (
                    <span className="metric-chip">
                      <Loader2 className="h-2.5 w-2.5 animate-spin" />
                      {phase === "analysis" ? "Drafting mechanism" : "Checking market context"}
                    </span>
                  )}
                </CardDescription>
              </CardHeader>
            </Card>

            {/* Macro context */}
            {result.event_date && <MacroStrip eventDate={result.event_date} />}

            {/* Mechanism grid — skeleton until analysis stage completes */}
            {!result.analysis ? (
              <div className="grid gap-3 lg:grid-cols-3">
                <div className="space-y-3 lg:col-span-2">
                  {[1, 2].map((k) => (
                    <Card key={k}>
                      <CardHeader><Skeleton className="h-3 w-24" /></CardHeader>
                      <CardContent className="space-y-1.5">
                        <Skeleton className="h-3.5 w-full" />
                        <Skeleton className="h-3.5 w-5/6" />
                      </CardContent>
                    </Card>
                  ))}
                </div>
                <div className="space-y-3">
                  {[1, 2].map((k) => (
                    <Card key={k}>
                      <CardHeader><Skeleton className="h-3 w-20" /></CardHeader>
                      <CardContent className="space-y-1.5">
                        <Skeleton className="h-3.5 w-3/4" />
                        <Skeleton className="h-3.5 w-2/3" />
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </div>
            ) : (
              <div className="fade-in grid gap-3 lg:grid-cols-3">
                <div className="space-y-3 lg:col-span-2">
                  <Card className="overflow-hidden">
                    <CardHeader className="border-b border-border/60 bg-secondary/35"><SectionLabel>What Changed</SectionLabel></CardHeader>
                    <CardContent>
                      <p className="text-[13px] leading-relaxed">{result.analysis.what_changed}</p>
                    </CardContent>
                  </Card>
                  <Card className="overflow-hidden">
                    <CardHeader className="border-b border-border/60 bg-secondary/35"><SectionLabel>Mechanism Summary</SectionLabel></CardHeader>
                    <CardContent>
                      <p className="text-[13px] leading-relaxed whitespace-pre-line">{result.analysis.mechanism_summary}</p>
                    </CardContent>
                  </Card>
                  {result.analysis.transmission_chain && result.analysis.transmission_chain.length > 0 && (
                    <Card className="overflow-hidden">
                      <CardHeader className="border-b border-border/60 bg-secondary/35">
                        <SectionLabel>Transmission Chain</SectionLabel>
                      </CardHeader>
                      <CardContent>
                        <div className="flex flex-col gap-0">
                          {result.analysis.transmission_chain.map((step, i) => (
                            <div key={i} className="flex items-start gap-2.5">
                              <div className="flex flex-col items-center shrink-0 pt-0.5">
                                <div className={cn(
                                  "flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold",
                                  i === 0 && "bg-foreground/10 text-foreground",
                                  i > 0 && i < (result.analysis.transmission_chain?.length ?? 0) - 1 && "bg-secondary text-muted-foreground",
                                  i === (result.analysis.transmission_chain?.length ?? 0) - 1 && "bg-foreground/10 text-foreground",
                                )}>
                                  {i + 1}
                                </div>
                                {i < (result.analysis.transmission_chain?.length ?? 0) - 1 && (
                                  <div className="w-px h-3 bg-border" />
                                )}
                              </div>
                              <p className="text-[12px] leading-relaxed text-foreground/85 pb-1">{step}</p>
                            </div>
                          ))}
                        </div>
                      </CardContent>
                    </Card>
                  )}
                  {result.analysis.assets_to_watch.length > 0 && (
                    <Card className="overflow-hidden">
                      <CardHeader className="border-b border-border/60 bg-secondary/35"><SectionLabel>Assets to Watch</SectionLabel></CardHeader>
                      <CardContent>
                        <div className="flex flex-wrap gap-1">
                          {result.analysis.assets_to_watch.map((a) => (
                            <Badge key={a} variant="outline" className="font-num">{a}</Badge>
                          ))}
                        </div>
                      </CardContent>
                    </Card>
                  )}
                </div>

                <div className="space-y-3">
                  <Card className="overflow-hidden">
                    <CardHeader className="border-b border-border/60 bg-secondary/35"><SectionLabel>Beneficiaries</SectionLabel></CardHeader>
                    <CardContent>
                      {result.analysis.beneficiaries.length > 0 ? (
                        <ul className="space-y-0.5">
                          {result.analysis.beneficiaries.map((b) => (
                            <li key={b} className="flex items-center gap-1.5 text-[13px]">
                              <TrendingUp className="h-3 w-3 shrink-0 val-pos" />
                              {b}
                            </li>
                          ))}
                        </ul>
                      ) : (
                      <p className="text-2xs leading-5 text-muted-foreground">No clear beneficiaries identified yet.</p>
                      )}
                    </CardContent>
                  </Card>
                  <Card className="overflow-hidden">
                    <CardHeader className="border-b border-border/60 bg-secondary/35"><SectionLabel>Losers</SectionLabel></CardHeader>
                    <CardContent>
                      {result.analysis.losers.length > 0 ? (
                        <ul className="space-y-0.5">
                          {result.analysis.losers.map((l) => (
                            <li key={l} className="flex items-center gap-1.5 text-[13px]">
                              <TrendingDown className="h-3 w-3 shrink-0 val-neg" />
                              {l}
                            </li>
                          ))}
                        </ul>
                      ) : (
                      <p className="text-2xs leading-5 text-muted-foreground">No clear losers identified yet.</p>
                      )}
                    </CardContent>
                  </Card>
                </div>
              </div>
            )}

            {/* Market check — skeleton until market stage completes */}
            <Separator />
            {!result.market ? (
              <div className="space-y-2">
                <Skeleton className="h-3 w-24" />
                <div className="flex gap-1.5 overflow-hidden">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-12 w-28 shrink-0 rounded-lg" />
                  ))}
                </div>
              </div>
            ) : (
              <div className="fade-in space-y-2">
                <div className="flex items-center justify-between">
                  <SectionLabel>Market Check</SectionLabel>
                  <span className="font-num text-2xs text-muted-foreground">
                    {result.market.tickers.length} ticker{result.market.tickers.length !== 1 && "s"}
                  </span>
                </div>
                <MarketCards tickers={result.market.tickers} eventDate={result.event_date ?? undefined} />
              </div>
            )}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
