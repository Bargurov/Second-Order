import { useState, useEffect, useCallback, useRef } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { Sparkline } from "@/components/ui/sparkline";
import { MarketBackdropStrip } from "@/components/ui/market-backdrop-strip";
import { TickerDetailPanel } from "@/components/ui/ticker-detail-panel";
import { TransmissionChain } from "@/components/ui/transmission-chain";
import { IfPersistsSection } from "@/components/ui/if-persists";
import {
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
  Check,
} from "lucide-react";
import { api, type AnalyzeResponse, type Ticker, type CurrencyChannel, type PolicySensitivity, type InventoryContext, type HistoricalAnalog } from "@/lib/api";
import { cn } from "@/lib/utils";
import { pct } from "@/lib/ticker-utils";

/*
  Tonal hierarchy (from Stitch reference):
    Page background:   #0a0a0f  (body / main)
    Big section card:  #13131a  (bg-surface-container-low)
    Inner card:        #242533  (bg-surface-container-highest)
*/

// ---------------------------------------------------------------------------
// Confidence — three clearly distinct muted colours
// ---------------------------------------------------------------------------

const CONFIDENCE: Record<string, {
  icon: React.ElementType;
  dot: string;
  text: string;
  bg: string;
  label: string;
}> = {
  high: {
    icon: ShieldCheck,
    dot: "bg-[#6ec6a5]",
    text: "text-[#6ec6a5]",
    bg: "bg-[#6ec6a5]/8",
    label: "High",
  },
  medium: {
    icon: Shield,
    dot: "bg-[#a89f91]",
    text: "text-[#a89f91]",
    bg: "bg-[#a89f91]/8",
    label: "Medium",
  },
  low: {
    icon: ShieldAlert,
    dot: "bg-[#c07070]",
    text: "text-[#c07070]",
    bg: "bg-[#c07070]/8",
    label: "Low",
  },
};

// Shared card class for big section cards (bg-surface-container-low)
const SECTION_CARD = "bg-surface-container-low rounded-xl shadow-[inset_0_0_0_1px_rgba(71,70,86,0.35),0_4px_12px_rgba(0,0,0,0.2)]";
// Inner card (bg-surface-container-highest)
const INNER_CARD = "bg-surface-container-highest rounded-lg";

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant mb-4 flex items-center gap-2">
      <span className="w-1 h-3 bg-primary rounded-full" />
      {children}
    </h4>
  );
}

// ---------------------------------------------------------------------------
// Currency Transmission block
// ---------------------------------------------------------------------------

function CurrencyChannelBlock({ data }: { data: CurrencyChannel }) {
  if (!data.pair || !data.mechanism) return null;
  return (
    <div className={cn(SECTION_CARD, "p-5")}>
      <div className="flex items-center gap-3 mb-3">
        <div className="w-8 h-8 rounded-lg bg-surface-container-highest flex items-center justify-center shrink-0">
          <span className="text-primary text-sm font-bold">FX</span>
        </div>
        <div>
          <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">Currency Transmission</h4>
          <span className="text-[13px] font-headline font-bold text-on-surface">{data.pair}</span>
        </div>
      </div>
      <p className="text-[12px] text-on-surface-variant leading-relaxed mb-3">{data.mechanism}</p>
      {(data.beneficiaries || data.squeezed) && (
        <div className="grid grid-cols-2 gap-3">
          {data.beneficiaries && (
            <div className={cn(INNER_CARD, "p-3 border-l-2 border-primary/50")}>
              <span className="text-[9px] font-bold uppercase tracking-widest text-primary/70 block mb-1">FX Beneficiaries</span>
              <p className="text-[11px] text-on-surface leading-relaxed">{data.beneficiaries}</p>
            </div>
          )}
          {data.squeezed && (
            <div className={cn(INNER_CARD, "p-3 border-l-2 border-error-dim/50")}>
              <span className="text-[9px] font-bold uppercase tracking-widest text-error-dim/70 block mb-1">FX Squeezed</span>
              <p className="text-[11px] text-on-surface leading-relaxed">{data.squeezed}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Monetary Policy Sensitivity block
// ---------------------------------------------------------------------------

const STANCE_STYLE: Record<string, { icon: string; color: string; bg: string }> = {
  reinforced: { icon: "↗", color: "text-primary", bg: "bg-primary/8" },
  fighting:   { icon: "↘", color: "text-error-dim", bg: "bg-error-dim/8" },
  neutral:    { icon: "→", color: "text-on-surface-variant", bg: "bg-surface-container-highest" },
};

function PolicySensitivityBlock({ data }: { data: PolicySensitivity }) {
  if (!data.stance || !data.explanation) return null;
  const style = STANCE_STYLE[data.stance] ?? STANCE_STYLE.neutral;
  const label = data.stance === "reinforced" ? "Reinforced by rates"
    : data.stance === "fighting" ? "Fighting current rates"
    : "Rates-neutral";
  return (
    <div className={cn("flex items-start gap-3 rounded-xl px-5 py-4", style.bg, "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.2)]")}>
      <span className={cn("text-lg font-bold leading-none mt-0.5", style.color)}>{style.icon}</span>
      <div className="min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className={cn("text-[10px] font-bold uppercase tracking-widest", style.color)}>{label}</span>
          {data.regime && (
            <span className="text-[9px] text-on-surface-variant/50">{data.regime}</span>
          )}
        </div>
        <p className="text-[12px] text-on-surface-variant leading-relaxed">{data.explanation}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inventory / Supply Context block
// ---------------------------------------------------------------------------

const INV_STYLE: Record<string, { icon: string; color: string; bg: string }> = {
  tight:       { icon: "▲", color: "text-error-dim", bg: "bg-error-dim/8" },
  comfortable: { icon: "▼", color: "text-primary", bg: "bg-primary/8" },
  neutral:     { icon: "●", color: "text-on-surface-variant", bg: "bg-surface-container-highest" },
};

function InventoryContextBlock({ data }: { data: InventoryContext }) {
  if (!data.status || !data.explanation) return null;
  const style = INV_STYLE[data.status] ?? INV_STYLE.neutral;
  const label = data.status === "tight" ? "Inventory-tight"
    : data.status === "comfortable" ? "Inventory-comfortable"
    : "Inventory-neutral";
  return (
    <div className={cn("flex items-start gap-3 rounded-xl px-5 py-4", style.bg, "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.2)]")}>
      <span className={cn("text-sm font-bold leading-none mt-1", style.color)}>{style.icon}</span>
      <div className="min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className={cn("text-[10px] font-bold uppercase tracking-widest", style.color)}>{label}</span>
          {data.proxy_label && (
            <span className="text-[9px] text-on-surface-variant/50">via {data.proxy_label}</span>
          )}
          {data.return_20d != null && (
            <span className={cn("text-[9px] font-bold font-num", data.return_20d > 0 ? "text-error-dim" : data.return_20d < 0 ? "text-primary" : "text-on-surface-variant")}>
              {data.return_20d >= 0 ? "+" : ""}{data.return_20d.toFixed(1)}% 20d
            </span>
          )}
        </div>
        <p className="text-[12px] text-on-surface-variant leading-relaxed">{data.explanation}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Historical Analogs block
// ---------------------------------------------------------------------------

const DECAY_STYLE: Record<string, { color: string; bg: string; label: string }> = {
  Accelerating: { color: "text-error-dim",             bg: "bg-error-dim/10",        label: "Accelerating" },
  Holding:      { color: "text-on-surface-variant",    bg: "bg-surface-container",   label: "Holding"      },
  Fading:       { color: "text-primary/70",            bg: "bg-primary/8",           label: "Fading"       },
  Reversed:     { color: "text-error",                 bg: "bg-error/10",            label: "Reversed"     },
  Unknown:      { color: "text-on-surface-variant/30", bg: "bg-transparent",         label: "Unknown"      },
};

function AnalogCard({ analog, rank }: { analog: HistoricalAnalog; rank: number }) {
  const decay = DECAY_STYLE[analog.decay] ?? DECAY_STYLE.Unknown;
  return (
    <div className={cn(INNER_CARD, "p-4 flex flex-col")}>
      {/* Rank + headline + date */}
      <div className="flex items-start gap-2 mb-2.5">
        <span className="shrink-0 text-[10px] font-bold tabular-nums text-on-surface-variant/35 mt-px w-4">
          {rank}.
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[12px] font-bold text-on-surface leading-snug line-clamp-2">
            {analog.headline}
          </p>
          {analog.event_date && (
            <span className="text-[9px] text-on-surface-variant/35 mt-0.5 block tabular-nums">
              {analog.event_date}
            </span>
          )}
        </div>
      </div>

      {/* Classification badges */}
      <div className="flex items-center gap-1.5 mb-3">
        <span className="text-[8px] px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant/60 font-bold uppercase tracking-widest">
          {analog.stage}
        </span>
        <span className="text-[8px] px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant/60 font-bold uppercase tracking-widest">
          {analog.persistence}
        </span>
      </div>

      {/* Follow-through metrics — 3-column comparison grid */}
      <div className="grid grid-cols-3 gap-x-3 py-3 border-t border-b border-outline-variant/10 mb-3">
        <div>
          <span className="text-[8px] text-on-surface-variant/40 uppercase tracking-widest block mb-1">5d return</span>
          {analog.return_5d != null ? (
            <span className={cn(
              "text-[14px] font-bold font-num leading-none",
              analog.return_5d > 0 ? "text-primary" : analog.return_5d < 0 ? "text-error-dim" : "text-on-surface-variant",
            )}>
              {analog.return_5d >= 0 ? "+" : ""}{analog.return_5d.toFixed(1)}%
            </span>
          ) : (
            <span className="text-[13px] text-on-surface-variant/25 font-num">—</span>
          )}
        </div>
        <div>
          <span className="text-[8px] text-on-surface-variant/40 uppercase tracking-widest block mb-1">20d return</span>
          {analog.return_20d != null ? (
            <span className={cn(
              "text-[14px] font-bold font-num leading-none",
              analog.return_20d > 0 ? "text-primary" : analog.return_20d < 0 ? "text-error-dim" : "text-on-surface-variant",
            )}>
              {analog.return_20d >= 0 ? "+" : ""}{analog.return_20d.toFixed(1)}%
            </span>
          ) : (
            <span className="text-[13px] text-on-surface-variant/25 font-num">—</span>
          )}
        </div>
        <div>
          <span className="text-[8px] text-on-surface-variant/40 uppercase tracking-widest block mb-1">Pattern</span>
          <span className={cn(
            "inline-block text-[8px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded leading-none",
            decay.bg, decay.color,
          )}>
            {decay.label}
          </span>
        </div>
      </div>

      {/* Match reason */}
      {analog.match_reason && (
        <p className="text-[10px] text-on-surface-variant/40 leading-relaxed mt-auto">
          {analog.match_reason}
        </p>
      )}
    </div>
  );
}

function HistoricalAnalogsBlock({ analogs }: { analogs: HistoricalAnalog[] }) {
  if (!analogs || analogs.length === 0) return null;
  const count = analogs.length;
  return (
    <div className={cn(SECTION_CARD, "p-6")}>
      <div className="flex items-start justify-between mb-5">
        <div className="flex items-center gap-2">
          <span className="w-1 h-3 bg-primary rounded-full shrink-0" />
          <div>
            <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">
              Historical Analogs
            </h4>
            <p className="text-[10px] text-on-surface-variant/40 mt-0.5">
              {count === 1 ? "Closest matching past event" : `Top ${count} matching past events`} · follow-through
            </p>
          </div>
        </div>
        <span className="text-[9px] tabular-nums text-on-surface-variant/25 mt-0.5">
          {count} of 3
        </span>
      </div>
      <div className={cn(
        "grid gap-3",
        count === 1 && "grid-cols-1",
        count === 2 && "grid-cols-1 md:grid-cols-2",
        count >= 3 && "grid-cols-1 md:grid-cols-3",
      )}>
        {analogs.map((a, i) => (
          <AnalogCard key={i} analog={a} rank={i + 1} />
        ))}
      </div>
    </div>
  );
}

// Ticker cards — inner level (#242533)
// ---------------------------------------------------------------------------

function isSupporting(t: Ticker): boolean {
  return t.direction_tag === "supporting" || (t.direction_tag?.startsWith("supports") ?? false);
}
function isContradicting(t: Ticker): boolean {
  return t.direction_tag === "contradicting" || (t.direction_tag?.startsWith("contradicts") ?? false);
}

function directionBadge(t: Ticker): { label: string; cls: string } {
  if (isSupporting(t)) return { label: "Confirmed", cls: "bg-primary-container/40 text-primary" };
  if (isContradicting(t)) return { label: "Inverted", cls: "bg-error-container/30 text-error-dim" };
  return { label: "Pending", cls: "bg-outline-variant/20 text-on-surface-variant" };
}

function TickerCard({ ticker, selected, onToggle }: { ticker: Ticker; selected: boolean; onToggle: () => void }) {
  if (ticker.label === "needs more evidence") {
    return (
      <div className={cn(INNER_CARD, "p-4 opacity-40")}>
        <h5 className="text-xs font-bold text-on-surface">{ticker.symbol}</h5>
        <p className="text-[10px] text-on-surface-variant italic">Pending</p>
      </div>
    );
  }
  const badge = directionBadge(ticker);
  const r5 = ticker.return_5d;
  return (
    <button
      onClick={onToggle}
      className={cn(
        INNER_CARD, "p-4 text-left transition-all w-full",
        selected ? "shadow-[inset_0_0_0_1px_rgba(147,209,211,0.4)]" : "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.15)]",
      )}
    >
      <div className="flex justify-between items-start mb-2">
        <div>
          <h5 className="text-xs font-bold text-on-surface">{ticker.symbol}</h5>
          <p className="text-[10px] text-on-surface-variant">{ticker.label || ticker.role}</p>
        </div>
        <span className={cn("text-[10px] px-2 py-0.5 rounded-full font-bold", badge.cls)}>{badge.label}</span>
      </div>
      <div className="flex items-end justify-between">
        <span className="text-xl font-headline font-extrabold text-on-surface">{pct(r5)}</span>
        {ticker.spark && ticker.spark.length > 2 && (
          <div className="w-20 h-8"><Sparkline data={ticker.spark} width={80} height={32} direction={r5} /></div>
        )}
      </div>
      {r5 != null && (
        <div className={cn("mt-2 text-[10px] font-bold", r5 > 0 ? "text-primary" : r5 < 0 ? "text-error-dim" : "text-on-surface-variant")}>
          {r5 >= 0 ? "+" : ""}{r5.toFixed(2)}% 5d
        </div>
      )}
      <ChevronDown className={cn("h-3 w-3 text-on-surface-variant/40 mt-1 mx-auto transition-transform", selected && "rotate-180")} />
    </button>
  );
}

function MarketSection({ tickers, eventDate }: { tickers: Ticker[]; eventDate?: string }) {
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const selectedTicker = tickers.find((t) => t.symbol === selectedSymbol);
  if (tickers.length === 0) return <p className="text-xs text-on-surface-variant text-center py-4">No market data returned.</p>;
  const withDir = tickers.filter((t) => t.direction_tag != null);
  const supportCount = withDir.filter(isSupporting).length;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {tickers.map((t) => (
          <TickerCard key={t.symbol} ticker={t} selected={selectedSymbol === t.symbol} onToggle={() => setSelectedSymbol((s) => (s === t.symbol ? null : t.symbol))} />
        ))}
      </div>
      {selectedTicker && selectedTicker.label !== "needs more evidence" && (
        <TickerDetailPanel ticker={selectedTicker} eventDate={eventDate} extra={{ label: selectedTicker.label, direction_tag: selectedTicker.direction_tag, return_1d: selectedTicker.return_1d, volume_ratio: selectedTicker.volume_ratio, vs_xle_5d: selectedTicker.vs_xle_5d }} />
      )}
      {withDir.length > 0 && (
        <p className="text-[10px] text-on-surface-variant">
          Hypothesis: <span className={cn("font-bold", supportCount === withDir.length && "text-primary", supportCount === 0 && "text-error")}>{supportCount}/{withDir.length}</span> tickers confirmed
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function AnalysisSkeleton() {
  return (
    <div className="space-y-8 pb-4">
      <div className={cn(SECTION_CARD, "p-10")}>
        <Skeleton className="h-3 w-48 bg-surface-container-highest mx-auto mb-8" />
        <div className="flex justify-between">
          {[1, 2, 3, 4].map((k) => (
            <div key={k} className="flex flex-col items-center gap-3">
              <Skeleton className="h-20 w-20 rounded-full bg-surface-container-highest" />
              <Skeleton className="h-3 w-24 bg-surface-container-highest" />
            </div>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-8">
        <Skeleton className={cn("h-48", SECTION_CARD)} />
        <Skeleton className={cn("h-48", SECTION_CARD)} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

interface AnalysisViewProps {
  initialHeadline?: string;
  initialContext?: string;
  onHeadlineConsumed?: () => void;
  onBack?: () => void;
}

type Phase = "idle" | "classify" | "analysis" | "market" | "complete";

export function AnalysisView({ initialHeadline, initialContext, onHeadlineConsumed, onBack }: AnalysisViewProps) {
  const [headline, setHeadline] = useState("");
  const [eventDate] = useState("");
  const contextRef = useRef<string | undefined>(initialContext);
  const eventDateRef = useRef(eventDate);
  eventDateRef.current = eventDate;
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const loading = phase !== "idle" && phase !== "complete";

  useEffect(() => () => { abortRef.current?.abort(); }, []);

  const submit = useCallback(async (h?: string) => {
    const text = (h ?? headline).trim();
    if (!text) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setHeadline(text);
    setPhase("classify");
    setError(null);
    setResult(null);
    let partial: Partial<AnalyzeResponse> = { headline: text };
    try {
      await api.analyzeStream(
        { headline: text, event_date: eventDateRef.current || undefined, event_context: contextRef.current || undefined },
        (stage, data) => {
          if (ctrl.signal.aborted) return;
          if (stage === "classify") {
            partial = { ...partial, stage: data.stage as string, persistence: data.persistence as string };
            setResult(partial as AnalyzeResponse);
            setPhase("analysis");
          } else if (stage === "analysis") {
            partial = { ...partial, analysis: data.analysis as AnalyzeResponse["analysis"], is_mock: data.is_mock as boolean };
            setResult(partial as AnalyzeResponse);
            setPhase("market");
          } else if (stage === "complete") {
            setResult(data as unknown as AnalyzeResponse);
            setPhase("complete");
          }
        },
        ctrl.signal,
      );
      if (!ctrl.signal.aborted) setPhase((p) => (p === "complete" ? p : "complete"));
    } catch (e) {
      if (ctrl.signal.aborted) return;
      setError(e instanceof Error ? e.message : "Analysis failed.");
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
    ? (CONFIDENCE[result.analysis.confidence] ?? CONFIDENCE.low)
    : null;
  const ConfIcon = conf?.icon ?? Shield;

  const isLowSignal = result?.analysis
    && (result.analysis.mechanism_summary || "").toLowerCase().includes("insufficient evidence")
    && result.analysis.beneficiaries.length === 0
    && result.analysis.losers.length === 0;

  return (
    <div className="pb-8">
      {/* ── TOP AREA ── */}
      <div className="mb-8">
        {onBack && (
          <button onClick={onBack} className="group flex items-center gap-2 mb-5 text-on-surface-variant hover:text-primary transition-colors">
            <span className="w-8 h-8 flex items-center justify-center rounded-lg bg-surface-container-highest group-hover:bg-surface-bright transition-colors">
              <ArrowLeft className="h-4 w-4" />
            </span>
            <span className="text-[10px] font-bold uppercase tracking-[0.15em]">Market Overview</span>
          </button>
        )}

        {result ? (
          <h1 className="font-headline text-[22px] font-extrabold tracking-tighter text-on-surface leading-tight max-w-3xl">
            {result.headline}
          </h1>
        ) : (
          <input
            type="text"
            placeholder="Paste a headline to analyze..."
            value={headline}
            onChange={(e) => setHeadline(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            className="w-full bg-transparent font-headline text-[22px] font-extrabold tracking-tighter text-primary placeholder:text-on-surface-variant/25 focus:outline-none"
          />
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {result?.stage && (
            <span className="text-[9px] px-2 py-0.5 rounded bg-surface-container-highest text-on-surface-variant font-bold uppercase tracking-widest">
              {result.stage}
            </span>
          )}
          {result?.persistence && (
            <span className="text-[9px] px-2 py-0.5 rounded bg-surface-container-highest text-on-surface-variant font-bold uppercase tracking-widest">
              {result.persistence}
            </span>
          )}
          {result?.is_mock && (
            <span className="text-[9px] px-2 py-0.5 rounded bg-error-container/30 text-error font-bold uppercase tracking-widest">Mock</span>
          )}
          {conf && result?.analysis && (
            <span className={cn("inline-flex items-center gap-1.5 text-[9px] px-2.5 py-0.5 rounded-full font-bold uppercase tracking-widest", conf.bg, conf.text)}>
              <span className={cn("w-1.5 h-1.5 rounded-full", conf.dot)} />
              <ConfIcon className="h-3 w-3" />
              {conf.label}
            </span>
          )}
          {result?.event_date && (
            <span className="text-[9px] text-on-surface-variant/40 ml-1">{result.event_date}</span>
          )}
          {loading && (
            <span className="inline-flex items-center gap-1 text-[9px] text-primary font-bold ml-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              {phase === "analysis" ? "Mechanism" : "Market"}
            </span>
          )}
        </div>
      </div>

      {/* ── ERROR ── */}
      {error && (
        <div className="mb-8 bg-error-container/15 rounded-xl p-4 flex items-start gap-3 shadow-[inset_0_0_0_1px_rgba(187,85,81,0.2)]">
          <AlertTriangle className="h-4 w-4 text-error-dim shrink-0 mt-0.5" />
          <div>
            <p className="text-[11px] font-bold text-error-dim">Analysis unavailable</p>
            <p className="text-[10px] text-on-surface-variant mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* ── EMPTY STATE ── */}
      {phase === "idle" && !result && !error && (
        <div className="flex items-center justify-center py-24">
          <div className="text-center space-y-3">
            <div className="mx-auto w-14 h-14 rounded-full bg-surface-container-highest flex items-center justify-center">
              <Eye className="h-6 w-6 text-on-surface-variant/30" />
            </div>
            <p className="text-sm font-headline font-bold text-on-surface/80">No active analysis</p>
            <p className="text-[11px] text-on-surface-variant/60 max-w-xs mx-auto leading-relaxed">
              Navigate from Market Overview or paste a headline above.
            </p>
          </div>
        </div>
      )}

      {/* ── SKELETON ── */}
      {phase === "classify" && !result && <AnalysisSkeleton />}

      {/* ── RESULTS ── */}
      {result && (
        <div className="space-y-8">

          {/* Market backdrop — compact secondary block fed from /market-context */}
          <section className={cn(SECTION_CARD, "px-6 py-3")}>
            <MarketBackdropStrip />
          </section>


          {/* ── STATE A: Strong signal ── */}
          {result.analysis && !isLowSignal && (
            <div className="space-y-8">
              {/* Transmission chain — big section card */}
              {result.analysis.transmission_chain && result.analysis.transmission_chain.length > 0 && (
                <section className={cn(SECTION_CARD, "p-10 relative overflow-hidden")}>
                  <div className="absolute top-0 right-0 w-64 h-64 bg-primary/4 blur-[100px] -mr-32 -mt-32" />
                  <h3 className="text-[10px] font-bold uppercase tracking-[0.3em] text-on-surface-variant mb-10 text-center relative z-10">
                    Event Transmission Architecture
                  </h3>
                  <div className="relative z-10">
                    <TransmissionChain steps={result.analysis.transmission_chain} />
                  </div>
                </section>
              )}

              {/* Two-column: What Changed + Mechanism | Beneficiaries + Losers */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Left — big section card, inner text */}
                <div className={cn(SECTION_CARD, "p-6 space-y-5")}>
                  <div>
                    <SectionLabel>What Changed</SectionLabel>
                    <ul className="space-y-2.5">
                      {result.analysis.what_changed.split(/[.!]\s+/).filter(Boolean).map((s, i) => (
                        <li key={i} className="flex items-start gap-2.5">
                          <Check className="h-3.5 w-3.5 text-primary shrink-0 mt-0.5" />
                          <p className="text-[12px] text-on-surface leading-relaxed">{s.trim().replace(/\.$/, "")}.</p>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="pt-5 border-t border-outline-variant/10">
                    <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant mb-2.5">Mechanism Summary</h4>
                    <p className="text-[12px] text-on-surface-variant/80 leading-relaxed italic whitespace-pre-line">
                      {result.analysis.mechanism_summary}
                    </p>
                  </div>
                </div>

                {/* Right — big section card, inner cards (#242533) */}
                <div className={cn(SECTION_CARD, "p-6 space-y-5")}>
                  <div>
                    <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant mb-3">Core Beneficiaries</h4>
                    {result.analysis.beneficiaries.length > 0 ? (
                      <div className="grid grid-cols-2 gap-2.5">
                        {result.analysis.beneficiaries.map((b) => (
                          <div key={b} className={cn(INNER_CARD, "p-3 border-l-2 border-primary/60 hover:border-primary transition-colors")}>
                            <div className="flex justify-between items-center">
                              <span className="font-headline font-bold text-[13px] text-on-surface">{b}</span>
                              <TrendingUp className="h-3.5 w-3.5 text-primary/60" />
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-[10px] text-on-surface-variant/50">None identified.</p>
                    )}
                  </div>
                  <div>
                    <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant mb-3">Projected Losers</h4>
                    {result.analysis.losers.length > 0 ? (
                      <div className="grid grid-cols-2 gap-2.5">
                        {result.analysis.losers.map((l) => (
                          <div key={l} className={cn(INNER_CARD, "p-3 border-l-2 border-error-dim/60 hover:border-error-dim transition-colors")}>
                            <div className="flex justify-between items-center">
                              <span className="font-headline font-bold text-[13px] text-on-surface">{l}</span>
                              <TrendingDown className="h-3.5 w-3.5 text-error-dim/60" />
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-[10px] text-on-surface-variant/50">None identified.</p>
                    )}
                  </div>
                </div>
              </div>

              {/* Currency Transmission */}
              {result.analysis.currency_channel && result.analysis.currency_channel.pair && (
                <CurrencyChannelBlock data={result.analysis.currency_channel} />
              )}

              {/* Monetary Policy Sensitivity */}
              {result.analysis.policy_sensitivity && result.analysis.policy_sensitivity.stance && (
                <PolicySensitivityBlock data={result.analysis.policy_sensitivity} />
              )}

              {/* Inventory / Supply Context */}
              {result.analysis.inventory_context && result.analysis.inventory_context.status && (
                <InventoryContextBlock data={result.analysis.inventory_context} />
              )}

              {/* If This Persists — big section card */}
              {result.analysis.if_persists && (
                <section className={cn(SECTION_CARD, "p-6")}>
                  <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant mb-4">
                    If This Persists: Second Order Effects
                  </h4>
                  <IfPersistsSection data={result.analysis.if_persists} />
                </section>
              )}

              {/* Historical Analogs */}
              {result.analysis.historical_analogs && result.analysis.historical_analogs.length > 0 && (
                <HistoricalAnalogsBlock analogs={result.analysis.historical_analogs} />
              )}
            </div>
          )}

          {/* ── STATE B: Low signal ── */}
          {result.analysis && isLowSignal && (
            <div className="space-y-6">
              <div className={cn(SECTION_CARD, "p-6")}>
                <SectionLabel>What Changed</SectionLabel>
                <p className="text-[12px] text-on-surface leading-relaxed">{result.analysis.what_changed}</p>
              </div>

              <div className={cn(SECTION_CARD, "px-5 py-4 flex items-center gap-3")}>
                <div className="w-6 h-6 rounded-full bg-surface-container-highest flex items-center justify-center shrink-0">
                  <AlertTriangle className="h-3.5 w-3.5 text-on-surface-variant/40" />
                </div>
                <div>
                  <p className="text-[11px] font-bold text-on-surface-variant/70">Insufficient signal</p>
                  <p className="text-[10px] text-on-surface-variant/50 mt-0.5">
                    No clear mechanism, beneficiaries, or losers identified for this event.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* ── ANALYSIS SKELETON (waiting) ── */}
          {!result.analysis && <AnalysisSkeleton />}

          {/* ── MARKET VALIDATION — big section card, ticker cards as inner (#242533) ── */}
          {!result.market ? (
            <div className="space-y-3">
              <Skeleton className="h-3 w-48 bg-surface-container-highest" />
              <div className="grid grid-cols-4 gap-4">
                {[1, 2, 3, 4].map((k) => <Skeleton key={k} className="h-28 rounded-xl bg-surface-container-low" />)}
              </div>
            </div>
          ) : (
            <section className={cn(SECTION_CARD, "p-6")}>
              <div className="flex items-center justify-between mb-4">
                <SectionLabel>Real-Time Market Validation</SectionLabel>
                <span className="text-[10px] text-on-surface-variant/40">
                  {result.market.tickers.length} ticker{result.market.tickers.length !== 1 && "s"}
                  {result.analysis?.assets_to_watch.length ? <> &middot; {result.analysis.assets_to_watch.join(", ")}</> : null}
                </span>
              </div>
              <MarketSection tickers={result.market.tickers} eventDate={result.event_date ?? undefined} />
            </section>
          )}
        </div>
      )}
    </div>
  );
}
