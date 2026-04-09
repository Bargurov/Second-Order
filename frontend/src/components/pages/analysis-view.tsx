import { useState, useEffect, useCallback, useRef, memo } from "react";
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
import { api, type AnalyzeResponse, type Ticker, type CurrencyChannel, type PolicySensitivity, type InventoryContext, type RealYieldContext, type PolicyConstraint, type ShockDecomposition, type ReactionFunctionDivergence, type SurpriseVsAnticipation, type TermsOfTrade, type TermsOfTradeExposure, type ReserveStress, type ReserveStressVulnerable, type ReserveStressInsulated, type HistoricalAnalog } from "@/lib/api";
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
// Real Yield / Breakeven Inflation Context block
// ---------------------------------------------------------------------------

const RY_STYLE: Record<string, { icon: string; color: string; bg: string; label: string }> = {
  confirm: { icon: "✓", color: "text-primary",          bg: "bg-primary/8",                  label: "Macro confirms" },
  tension: { icon: "⚠", color: "text-error-dim",        bg: "bg-error-dim/8",                label: "Macro check" },
  neutral: { icon: "→", color: "text-on-surface-variant", bg: "bg-surface-container-highest", label: "Macro inconclusive" },
  stale:   { icon: "·", color: "text-on-surface-variant/60", bg: "bg-surface-container-highest", label: "Macro unavailable" },
};

const RY_THESIS_LABEL: Record<string, string> = {
  inflationary:        "Inflationary thesis",
  disinflationary:     "Disinflationary thesis",
  rate_pressure_up:    "Hawkish rate-pressure thesis",
  rate_pressure_down:  "Dovish rate-pressure thesis",
};

function RealYieldContextBlock({ data }: { data: RealYieldContext }) {
  if (!data || !data.thesis || data.thesis === "none" || !data.alignment) return null;
  const style = RY_STYLE[data.alignment] ?? RY_STYLE.neutral;
  const thesisLabel = RY_THESIS_LABEL[data.thesis] ?? "Macro context";
  const fmt = (v: number | null | undefined) =>
    v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
  return (
    <div className={cn("flex items-start gap-3 rounded-xl px-5 py-4", style.bg, "shadow-[inset_0_0_0_1px_rgba(71,70,86,0.2)]")}>
      <span className={cn("text-lg font-bold leading-none mt-0.5", style.color)}>{style.icon}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <span className={cn("text-[10px] font-bold uppercase tracking-widest", style.color)}>{style.label}</span>
          <span className="text-[9px] text-on-surface-variant/50">{thesisLabel}</span>
          {data.regime && (
            <span className="text-[9px] text-on-surface-variant/40">· {data.regime}</span>
          )}
        </div>
        <p className="text-[12px] text-on-surface-variant leading-relaxed">{data.explanation}</p>
        {data.available && (
          <div className="flex items-center gap-3 mt-2 text-[9px] font-num text-on-surface-variant/60">
            <span>nom 5d <span className="text-on-surface/80">{fmt(data.nominal_5d)}</span></span>
            <span>real 5d <span className="text-on-surface/80">{fmt(data.real_proxy_5d)}</span></span>
            <span>BE 5d <span className="text-on-surface/80">{fmt(data.breakeven_proxy_5d)}</span></span>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Policy Constraint Engine block
// ---------------------------------------------------------------------------

const ROOM_STYLE: Record<string, { icon: string; color: string; bg: string; label: string }> = {
  ample:       { icon: "◆", color: "text-primary",            bg: "bg-primary/8",                  label: "Ample policy room" },
  limited:     { icon: "◇", color: "text-on-surface-variant", bg: "bg-surface-container-highest", label: "Limited policy room" },
  constrained: { icon: "▲", color: "text-error-dim",          bg: "bg-error-dim/8",                label: "Constrained" },
  mixed:       { icon: "◈", color: "text-on-surface-variant", bg: "bg-surface-container-highest", label: "Mixed mandate" },
  unknown:     { icon: "·", color: "text-on-surface-variant/60", bg: "bg-surface-container-highest", label: "Macro partial" },
};

function PolicyConstraintBlock({ data }: { data: PolicyConstraint }) {
  if (!data || !data.binding || !data.policy_room) return null;
  const room = data.policy_room;
  const style = ROOM_STYLE[room] ?? ROOM_STYLE.unknown;
  const bindingLabel = data.binding_label ?? data.binding;
  const isNone = data.binding === "none";

  return (
    <section className={cn(SECTION_CARD, "p-5")}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">
          Policy Constraint
        </h4>
        <div className="flex items-center gap-1.5">
          <span className={cn("text-xs font-bold leading-none", style.color)}>{style.icon}</span>
          <span className={cn("text-[9px] font-bold uppercase tracking-widest", style.color)}>
            {style.label}
          </span>
        </div>
      </div>

      {/* Binding + secondary chips */}
      <div className="flex items-start gap-3 mb-3 flex-wrap">
        <div className="min-w-0">
          <div className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mb-0.5">
            Binding
          </div>
          <div className={cn("text-[13px] font-bold", isNone ? "text-on-surface-variant" : "text-on-surface")}>
            {bindingLabel}
          </div>
        </div>
        {!!(data.secondary && data.secondary.length > 0) && (
          <div className="min-w-0 flex-1">
            <div className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mb-1">
              Secondary
            </div>
            <div className="flex flex-wrap gap-1.5">
              {data.secondary.map((sec) => (
                <span
                  key={sec.id}
                  className="inline-flex items-center gap-1 rounded-full bg-surface-container-highest px-2 py-0.5 text-[10px] text-on-surface-variant"
                  title={sec.rationale}
                >
                  <span className="font-bold text-on-surface/80">{sec.label}</span>
                  <span className="font-num text-on-surface-variant/50">{sec.score.toFixed(1)}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Why + reaction function */}
      {data.why && (
        <p className="text-[12px] text-on-surface leading-relaxed mb-2">{data.why}</p>
      )}
      {data.reaction_function && !isNone && (
        <p className="text-[11px] text-on-surface-variant leading-relaxed mb-3 italic">
          {data.reaction_function}
        </p>
      )}

      {/* Key markets */}
      {!!(data.key_markets && data.key_markets.length > 0) && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/50">
            Watch
          </span>
          {data.key_markets.map((m) => (
            <span
              key={m}
              className="font-num text-[10px] text-on-surface/80 bg-surface-container-highest rounded px-1.5 py-0.5"
            >
              {m}
            </span>
          ))}
          {data.stale && (
            <span className="text-[9px] text-on-surface-variant/50 italic">
              macro partial
            </span>
          )}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Real vs Nominal Shock Decomposition block
// ---------------------------------------------------------------------------

const SHOCK_STYLE: Record<string, { icon: string; color: string; bg: string }> = {
  nominal_yield: { icon: "≡", color: "text-on-surface-variant",    bg: "bg-surface-container-highest" },
  real_yield:    { icon: "▼", color: "text-primary",               bg: "bg-primary/8" },
  breakeven:     { icon: "↑", color: "text-error-dim",             bg: "bg-error-dim/8" },
  fx:            { icon: "$", color: "text-on-surface-variant",    bg: "bg-surface-container-highest" },
  commodity:     { icon: "◆", color: "text-error-dim",             bg: "bg-error-dim/8" },
  none:          { icon: "·", color: "text-on-surface-variant/60", bg: "bg-surface-container-highest" },
};

const SHOCK_CHANNEL_ORDER: Array<{ id: keyof NonNullable<ShockDecomposition["channels"]>; short: string }> = [
  { id: "nominal_yield", short: "Nominal" },
  { id: "real_yield",    short: "Real"    },
  { id: "breakeven",     short: "BE"      },
  { id: "fx",            short: "DXY"     },
  { id: "commodity",     short: "Cmdty"   },
];

function ShockDecompositionBlock({ data }: { data: ShockDecomposition }) {
  if (!data || !data.primary) return null;
  const style = SHOCK_STYLE[data.primary] ?? SHOCK_STYLE.none;
  const isNone = data.primary === "none";
  const fmt = (v: number | null | undefined) =>
    v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

  return (
    <section className={cn(SECTION_CARD, "p-5")}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">
          Shock Decomposition
        </h4>
        <div className="flex items-center gap-1.5">
          <span className={cn("text-xs font-bold leading-none", style.color)}>{style.icon}</span>
          <span className={cn("text-[9px] font-bold uppercase tracking-widest", style.color)}>
            {isNone ? "No clear shock" : "Primary driver"}
          </span>
        </div>
      </div>

      {/* Primary + secondary chips */}
      <div className="flex items-start gap-3 mb-3 flex-wrap">
        <div className="min-w-0">
          <div className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mb-0.5">
            Primary
          </div>
          <div className={cn("text-[13px] font-bold", isNone ? "text-on-surface-variant" : "text-on-surface")}>
            {data.primary_label ?? data.primary}
          </div>
        </div>
        {!!(data.secondary && data.secondary.length > 0) && (
          <div className="min-w-0 flex-1">
            <div className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mb-1">
              Secondary
            </div>
            <div className="flex flex-wrap gap-1.5">
              {data.secondary.map((s) => (
                <span
                  key={s.id}
                  className="inline-flex items-center gap-1 rounded-full bg-surface-container-highest px-2 py-0.5 text-[10px] text-on-surface-variant"
                  title={`${fmt(s.move_5d)} / 5d`}
                >
                  <span className="font-bold text-on-surface/80">{s.label}</span>
                  <span className="font-num text-on-surface-variant/50">{s.z.toFixed(1)}σ</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Empirical rationale + macro read */}
      {data.rationale && (
        <p className="text-[12px] text-on-surface leading-relaxed mb-2 font-num">
          {data.rationale}
        </p>
      )}
      {data.macro_read && (
        <p className="text-[11px] text-on-surface-variant leading-relaxed mb-3 italic">
          {data.macro_read}
        </p>
      )}

      {/* Channel grid — all five channels with magnitudes */}
      {data.channels && (
        <div className="grid grid-cols-5 gap-1.5 mb-3">
          {SHOCK_CHANNEL_ORDER.map((c) => {
            const ch = data.channels?.[c.id];
            const isPrimary = data.primary === c.id;
            return (
              <div
                key={c.id}
                className={cn(
                  "rounded px-2 py-1.5 text-center",
                  isPrimary ? "bg-primary/10" : "bg-surface-container-highest",
                )}
              >
                <div className="text-[8px] uppercase tracking-widest text-on-surface-variant/50">
                  {c.short}
                </div>
                <div
                  className={cn(
                    "text-[11px] font-num font-bold mt-0.5",
                    ch?.available ? "text-on-surface" : "text-on-surface-variant/30",
                  )}
                >
                  {ch?.available ? fmt(ch.move_5d) : "—"}
                </div>
                {ch?.available && (
                  <div className="text-[8px] text-on-surface-variant/50 font-num">
                    {ch.z.toFixed(1)}σ
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Key markets to watch */}
      {!!(data.key_markets && data.key_markets.length > 0) && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/50">
            Confirm / challenge
          </span>
          {data.key_markets.map((m) => (
            <span
              key={m}
              className="font-num text-[10px] text-on-surface/80 bg-surface-container-highest rounded px-1.5 py-0.5"
            >
              {m}
            </span>
          ))}
          {data.stale && (
            <span className="text-[9px] text-on-surface-variant/50 italic">
              macro partial
            </span>
          )}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Reaction Function Divergence block
// ---------------------------------------------------------------------------

const RFD_DIRECTION_STYLE: Record<string, { color: string; arrow: string }> = {
  hawkish: { color: "text-error-dim",             arrow: "↑" },
  dovish:  { color: "text-primary",               arrow: "↓" },
  neutral: { color: "text-on-surface-variant/60", arrow: "·" },
};

const RFD_DIVERGENCE_STYLE: Record<string, { icon: string; color: string; bg: string }> = {
  aligned: { icon: "◆", color: "text-primary",               bg: "bg-primary/8" },
  mild:    { icon: "◇", color: "text-on-surface-variant",    bg: "bg-surface-container-highest" },
  sharp:   { icon: "▲", color: "text-error-dim",             bg: "bg-error-dim/10" },
};

function ReactionFunctionDivergenceBlock({ data }: { data: ReactionFunctionDivergence }) {
  if (!data || !data.implied || !data.priced || !data.divergence) return null;
  const divStyle = RFD_DIVERGENCE_STYLE[data.divergence] ?? RFD_DIVERGENCE_STYLE.mild;
  const impliedStyle = RFD_DIRECTION_STYLE[data.implied] ?? RFD_DIRECTION_STYLE.neutral;
  const pricedStyle = RFD_DIRECTION_STYLE[data.priced] ?? RFD_DIRECTION_STYLE.neutral;

  return (
    <section className={cn(SECTION_CARD, "p-5")}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">
          Reaction Function Divergence
        </h4>
        <div className={cn("flex items-center gap-1.5 rounded-full px-2 py-0.5", divStyle.bg)}>
          <span className={cn("text-xs font-bold leading-none", divStyle.color)}>{divStyle.icon}</span>
          <span className={cn("text-[9px] font-bold uppercase tracking-widest", divStyle.color)}>
            {data.divergence_label ?? data.divergence}
          </span>
        </div>
      </div>

      {/* Implied vs priced — side-by-side */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div className="bg-surface-container-highest rounded px-3 py-2.5">
          <div className="flex items-center gap-1.5 mb-1">
            <span className={cn("text-[10px] font-bold leading-none", impliedStyle.color)}>
              {impliedStyle.arrow}
            </span>
            <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/50">
              Event implies
            </span>
          </div>
          <div className={cn("text-[12px] font-bold mb-1", impliedStyle.color)}>
            {data.implied_label ?? data.implied}
          </div>
          {data.implied_basis && (
            <p className="text-[10px] text-on-surface-variant/80 leading-snug">
              {data.implied_basis}
            </p>
          )}
        </div>

        <div className="bg-surface-container-highest rounded px-3 py-2.5">
          <div className="flex items-center gap-1.5 mb-1">
            <span className={cn("text-[10px] font-bold leading-none", pricedStyle.color)}>
              {pricedStyle.arrow}
            </span>
            <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/50">
              Markets pricing
            </span>
          </div>
          <div className={cn("text-[12px] font-bold mb-1", pricedStyle.color)}>
            {data.priced_label ?? data.priced}
          </div>
          {data.priced_basis && (
            <p className="text-[10px] text-on-surface-variant/80 leading-snug font-num">
              {data.priced_basis}
            </p>
          )}
        </div>
      </div>

      {/* Rationale + macro read */}
      {data.rationale && (
        <p className="text-[12px] text-on-surface leading-relaxed mb-2">
          {data.rationale}
        </p>
      )}
      {data.macro_read && (
        <p className="text-[11px] text-on-surface-variant leading-relaxed mb-3 italic">
          {data.macro_read}
        </p>
      )}

      {/* Key markets */}
      {!!(data.key_markets && data.key_markets.length > 0) && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/50">
            Confirm / challenge
          </span>
          {data.key_markets.map((m) => (
            <span
              key={m}
              className="font-num text-[10px] text-on-surface/80 bg-surface-container-highest rounded px-1.5 py-0.5"
            >
              {m}
            </span>
          ))}
          {data.stale && (
            <span className="text-[9px] text-on-surface-variant/50 italic">
              macro partial
            </span>
          )}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Surprise vs Anticipation Decomposition block
// ---------------------------------------------------------------------------

const SURPRISE_REGIME_STYLE: Record<string, { icon: string; color: string; bg: string }> = {
  surprise_shock:           { icon: "▲", color: "text-error-dim",             bg: "bg-error-dim/10" },
  anticipated_confirmation: { icon: "◆", color: "text-primary",               bg: "bg-primary/8" },
  uncertainty_resolution:   { icon: "◇", color: "text-primary/70",            bg: "bg-primary/6" },
  mixed:                    { icon: "·", color: "text-on-surface-variant",    bg: "bg-surface-container-highest" },
};

function SurpriseVsAnticipationBlock({ data }: { data: SurpriseVsAnticipation }) {
  if (!data || !data.regime) return null;
  const style = SURPRISE_REGIME_STYLE[data.regime] ?? SURPRISE_REGIME_STYLE.mixed;
  const sig = data.signals ?? {};
  const share = sig.intraday_share;
  const vix5d = sig.vix_change_5d;

  return (
    <section className={cn(SECTION_CARD, "p-5")}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">
          Surprise vs Anticipation
        </h4>
        <div className={cn("flex items-center gap-1.5 rounded-full px-2 py-0.5", style.bg)}>
          <span className={cn("text-xs font-bold leading-none", style.color)}>{style.icon}</span>
          <span className={cn("text-[9px] font-bold uppercase tracking-widest", style.color)}>
            {data.regime_label ?? data.regime}
          </span>
        </div>
      </div>

      {/* Rationale — one-line institutional read */}
      {data.rationale && (
        <p className="text-[12px] text-on-surface leading-relaxed mb-3">
          {data.rationale}
        </p>
      )}

      {/* Priced before vs changed on realisation — side-by-side */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div className="bg-surface-container-highest rounded px-3 py-2.5">
          <div className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mb-1">
            Priced before
          </div>
          <p className="text-[11px] text-on-surface/90 leading-snug">
            {data.priced_before ?? "—"}
          </p>
        </div>

        <div className="bg-surface-container-highest rounded px-3 py-2.5">
          <div className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mb-1">
            Changed on realisation
          </div>
          <p className="text-[11px] text-on-surface/90 leading-snug">
            {data.changed_on_realization ?? "—"}
          </p>
        </div>
      </div>

      {/* Signal strip — intraday share, vix 5d, stage */}
      {(share != null || vix5d != null || sig.stage) && (
        <div className="flex items-center gap-3 mb-3 text-[10px] text-on-surface-variant/70">
          {share != null && (
            <span className="font-num">
              <span className="text-on-surface-variant/40">intraday </span>
              {(share * 100).toFixed(0)}%
            </span>
          )}
          {vix5d != null && (
            <span className="font-num">
              <span className="text-on-surface-variant/40">VIX 5d </span>
              {vix5d >= 0 ? "+" : ""}{vix5d.toFixed(2)}
            </span>
          )}
          {sig.stage && (
            <span>
              <span className="text-on-surface-variant/40">stage </span>
              {sig.stage}
            </span>
          )}
        </div>
      )}

      {/* Key markets + stale indicator */}
      {!!(data.key_markets && data.key_markets.length > 0) && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/50">
            Confirm / challenge
          </span>
          {data.key_markets.map((m) => (
            <span
              key={m}
              className="font-num text-[10px] text-on-surface/80 bg-surface-container-highest rounded px-1.5 py-0.5"
            >
              {m}
            </span>
          ))}
          {data.stale && (
            <span className="text-[9px] text-on-surface-variant/50 italic">
              context partial
            </span>
          )}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Terms-of-Trade / External Vulnerability block
// ---------------------------------------------------------------------------

const TOT_CHANNEL_STYLE: Record<string, { icon: string; color: string; bg: string }> = {
  oil_import:       { icon: "▼", color: "text-error-dim",             bg: "bg-error-dim/10" },
  oil_export:       { icon: "▲", color: "text-primary",               bg: "bg-primary/8" },
  usd_funding:      { icon: "$", color: "text-error-dim",             bg: "bg-error-dim/10" },
  food_import:      { icon: "▼", color: "text-error-dim",             bg: "bg-error-dim/10" },
  industrial_metal: { icon: "◆", color: "text-primary",               bg: "bg-primary/8" },
  mixed:            { icon: "·", color: "text-on-surface-variant",    bg: "bg-surface-container-highest" },
  none:             { icon: "·", color: "text-on-surface-variant/60", bg: "bg-surface-container-highest" },
};

function ExposureRow({ exposure }: { exposure: TermsOfTradeExposure }) {
  const isWinner = exposure.role === "winner";
  return (
    <div className="flex items-start gap-2 py-1.5">
      <span
        className={cn(
          "mt-0.5 shrink-0 text-[9px] font-bold leading-none w-3",
          isWinner ? "text-primary" : "text-error-dim",
        )}
      >
        {isWinner ? "▲" : "▼"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-1.5">
          <span className="text-[12px] font-bold text-on-surface leading-tight">
            {exposure.country}
          </span>
          <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/40">
            {exposure.region}
          </span>
        </div>
        <p className="text-[10px] text-on-surface-variant/80 leading-snug mt-0.5">
          {exposure.rationale}
        </p>
      </div>
    </div>
  );
}

function TermsOfTradeBlock({ data }: { data: TermsOfTrade }) {
  if (!data || !data.dominant_channel) return null;
  if (data.dominant_channel === "none" && (!data.exposures || data.exposures.length === 0)) {
    return null;
  }
  const style = TOT_CHANNEL_STYLE[data.dominant_channel] ?? TOT_CHANNEL_STYLE.mixed;
  const sig = data.signals ?? {};
  const crude = sig.crude_5d;
  const dxy = sig.dxy_5d;

  const winners = (data.exposures ?? []).filter((e) => e.role === "winner");
  const losers = (data.exposures ?? []).filter((e) => e.role === "loser");

  return (
    <section className={cn(SECTION_CARD, "p-5")}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">
          Terms of Trade / External Vulnerability
        </h4>
        <div className={cn("flex items-center gap-1.5 rounded-full px-2 py-0.5", style.bg)}>
          <span className={cn("text-xs font-bold leading-none", style.color)}>{style.icon}</span>
          <span className={cn("text-[9px] font-bold uppercase tracking-widest", style.color)}>
            {data.dominant_channel_label ?? data.dominant_channel}
          </span>
        </div>
      </div>

      {/* Rationale — one-line institutional read */}
      {data.rationale && (
        <p className="text-[12px] text-on-surface leading-relaxed mb-3">
          {data.rationale}
        </p>
      )}

      {/* Winners / Losers — side-by-side columns */}
      {(winners.length > 0 || losers.length > 0) && (
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div className="bg-surface-container-highest rounded px-3 py-2.5">
            <div className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mb-1">
              External winners
            </div>
            {winners.length > 0 ? (
              <div className="divide-y divide-outline-variant/10">
                {winners.map((e) => (
                  <ExposureRow key={`${e.country}-${e.channel}`} exposure={e} />
                ))}
              </div>
            ) : (
              <p className="text-[10px] text-on-surface-variant/40 italic">None in frame</p>
            )}
          </div>

          <div className="bg-surface-container-highest rounded px-3 py-2.5">
            <div className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mb-1">
              External losers
            </div>
            {losers.length > 0 ? (
              <div className="divide-y divide-outline-variant/10">
                {losers.map((e) => (
                  <ExposureRow key={`${e.country}-${e.channel}`} exposure={e} />
                ))}
              </div>
            ) : (
              <p className="text-[10px] text-on-surface-variant/40 italic">None in frame</p>
            )}
          </div>
        </div>
      )}

      {/* Signal strip */}
      {(crude != null || dxy != null || sig.matched_theme) && (
        <div className="flex items-center gap-3 mb-3 text-[10px] text-on-surface-variant/70">
          {crude != null && (
            <span className="font-num">
              <span className="text-on-surface-variant/40">crude 5d </span>
              {crude >= 0 ? "+" : ""}{crude.toFixed(1)}%
            </span>
          )}
          {dxy != null && (
            <span className="font-num">
              <span className="text-on-surface-variant/40">DXY 5d </span>
              {dxy >= 0 ? "+" : ""}{dxy.toFixed(2)}
            </span>
          )}
          {sig.matched_theme && sig.matched_theme !== "none" && (
            <span>
              <span className="text-on-surface-variant/40">theme </span>
              {sig.matched_theme}
            </span>
          )}
        </div>
      )}

      {/* Key markets + stale indicator */}
      {!!(data.key_markets && data.key_markets.length > 0) && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/50">
            Confirm / challenge
          </span>
          {data.key_markets.map((m) => (
            <span
              key={m}
              className="font-num text-[10px] text-on-surface/80 bg-surface-container-highest rounded px-1.5 py-0.5"
            >
              {m}
            </span>
          ))}
          {data.stale && (
            <span className="text-[9px] text-on-surface-variant/50 italic">
              snapshots partial
            </span>
          )}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Current Account + FX Reserve Stress Overlay
// ---------------------------------------------------------------------------

const RS_CHANNEL_STYLE: Record<string, { icon: string; color: string; bg: string }> = {
  dual_oil_dollar:            { icon: "▼", color: "text-error-dim",             bg: "bg-error-dim/10" },
  oil_import_squeeze:         { icon: "▼", color: "text-error-dim",             bg: "bg-error-dim/10" },
  usd_funding_stress:         { icon: "$", color: "text-error-dim",             bg: "bg-error-dim/10" },
  food_importer_stress:       { icon: "▼", color: "text-error-dim",             bg: "bg-error-dim/10" },
  commodity_exporter_cushion: { icon: "▲", color: "text-primary",               bg: "bg-primary/8" },
  mixed:                      { icon: "·", color: "text-on-surface-variant",    bg: "bg-surface-container-highest" },
  none:                       { icon: "·", color: "text-on-surface-variant/60", bg: "bg-surface-container-highest" },
};

const RS_PRESSURE_STYLE: Record<string, { color: string; bg: string; label: string }> = {
  elevated:  { color: "text-error-dim",             bg: "bg-error-dim/15",           label: "Elevated"  },
  moderate:  { color: "text-on-surface",            bg: "bg-surface-container-highest", label: "Moderate"  },
  contained: { color: "text-on-surface-variant/70", bg: "bg-surface-container-highest", label: "Contained" },
};

const RS_DRIVER_LABEL: Record<string, string> = {
  dollar_rally:     "Dollar rally",
  credit_widening:  "Credit widening",
  oil_squeeze:      "Oil squeeze",
  real_yield_rise:  "Real yields up",
  dual_squeeze:     "Dual squeeze",
  risk_off_regime:  "Risk-off regime",
};

function ReserveStressExposureRow({
  name, region, rationale, score, scoreLabel, winner,
}: {
  name: string;
  region: string;
  rationale: string;
  score: number;
  scoreLabel: string;
  winner: boolean;
}) {
  return (
    <div className="flex items-start gap-2 py-1.5">
      <span
        className={cn(
          "mt-0.5 shrink-0 text-[9px] font-bold leading-none w-3",
          winner ? "text-primary" : "text-error-dim",
        )}
      >
        {winner ? "▲" : "▼"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-1.5">
          <span className="text-[12px] font-bold text-on-surface leading-tight">
            {name}
          </span>
          <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/40">
            {region}
          </span>
          <span
            className={cn(
              "ml-auto font-num text-[10px] tabular-nums shrink-0",
              winner ? "text-primary/70" : "text-error-dim/70",
            )}
            title={scoreLabel}
          >
            {score}/10
          </span>
        </div>
        <p className="text-[10px] text-on-surface-variant/80 leading-snug mt-0.5">
          {rationale}
        </p>
      </div>
    </div>
  );
}

function ReserveStressBlock({ data }: { data: ReserveStress }) {
  if (!data || !data.dominant_channel) return null;
  if (
    data.dominant_channel === "none"
    && (!data.vulnerable || data.vulnerable.length === 0)
    && (!data.insulated || data.insulated.length === 0)
  ) {
    return null;
  }

  const channelStyle = RS_CHANNEL_STYLE[data.dominant_channel] ?? RS_CHANNEL_STYLE.mixed;
  const pressureKey = data.pressure_label ?? "contained";
  const pressureStyle = RS_PRESSURE_STYLE[pressureKey] ?? RS_PRESSURE_STYLE.contained;
  const score = data.pressure_score ?? 0;
  const sig = data.signals ?? {};
  const crude = sig.crude_5d;
  const dxy = sig.dxy_5d;
  const credit = sig.credit_spread_5d;

  const vulnerable = (data.vulnerable ?? []) as ReserveStressVulnerable[];
  const insulated = (data.insulated ?? []) as ReserveStressInsulated[];

  // Collapse driver tags across the vulnerable list; they all share the
  // same driver set so pulling from the first entry is exact.
  const driverTags = vulnerable[0]?.drivers ?? [];

  return (
    <section className={cn(SECTION_CARD, "p-5")}>
      <div className="flex items-center justify-between mb-3 gap-3">
        <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">
          Current Account / FX Reserve Stress
        </h4>
        <div className="flex items-center gap-2 shrink-0">
          <div className={cn("flex items-center gap-1.5 rounded-full px-2 py-0.5", channelStyle.bg)}>
            <span className={cn("text-xs font-bold leading-none", channelStyle.color)}>
              {channelStyle.icon}
            </span>
            <span className={cn("text-[9px] font-bold uppercase tracking-widest", channelStyle.color)}>
              {data.dominant_channel_label ?? data.dominant_channel}
            </span>
          </div>
          <div className={cn(
            "flex items-center gap-1 rounded-full px-2 py-0.5",
            pressureStyle.bg,
          )}>
            <span className={cn(
              "font-num text-[10px] font-bold tabular-nums",
              pressureStyle.color,
            )}>
              {score}
            </span>
            <span className={cn(
              "text-[9px] font-bold uppercase tracking-widest",
              pressureStyle.color,
            )}>
              {pressureStyle.label}
            </span>
          </div>
        </div>
      </div>

      {/* Rationale */}
      {data.rationale && (
        <p className="text-[12px] text-on-surface leading-relaxed mb-3">
          {data.rationale}
        </p>
      )}

      {/* Driver tags */}
      {driverTags.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap mb-3">
          <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mr-1">
            Drivers
          </span>
          {driverTags.map((d) => (
            <span
              key={d}
              className="text-[10px] text-on-surface/80 bg-surface-container-highest rounded px-1.5 py-0.5"
            >
              {RS_DRIVER_LABEL[d] ?? d}
            </span>
          ))}
        </div>
      )}

      {/* Vulnerable / Insulated columns */}
      {(vulnerable.length > 0 || insulated.length > 0) && (
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div className="bg-surface-container-highest rounded px-3 py-2.5">
            <div className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mb-1">
              Most vulnerable
            </div>
            {vulnerable.length > 0 ? (
              <div className="divide-y divide-outline-variant/10">
                {vulnerable.map((e) => (
                  <ReserveStressExposureRow
                    key={`v-${e.country}`}
                    name={e.country}
                    region={e.region}
                    rationale={e.rationale}
                    score={e.vulnerability}
                    scoreLabel="Vulnerability score (0-10)"
                    winner={false}
                  />
                ))}
              </div>
            ) : (
              <p className="text-[10px] text-on-surface-variant/40 italic">None in frame</p>
            )}
          </div>

          <div className="bg-surface-container-highest rounded px-3 py-2.5">
            <div className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mb-1">
              Most insulated
            </div>
            {insulated.length > 0 ? (
              <div className="divide-y divide-outline-variant/10">
                {insulated.map((e) => (
                  <ReserveStressExposureRow
                    key={`i-${e.country}`}
                    name={e.country}
                    region={e.region}
                    rationale={e.rationale}
                    score={e.strength}
                    scoreLabel="Insulation score (0-10)"
                    winner={true}
                  />
                ))}
              </div>
            ) : (
              <p className="text-[10px] text-on-surface-variant/40 italic">None in frame</p>
            )}
          </div>
        </div>
      )}

      {/* Signal strip */}
      {(crude != null || dxy != null || credit != null) && (
        <div className="flex items-center gap-3 mb-3 text-[10px] text-on-surface-variant/70">
          {crude != null && (
            <span className="font-num">
              <span className="text-on-surface-variant/40">crude 5d </span>
              {crude >= 0 ? "+" : ""}{crude.toFixed(1)}%
            </span>
          )}
          {dxy != null && (
            <span className="font-num">
              <span className="text-on-surface-variant/40">DXY 5d </span>
              {dxy >= 0 ? "+" : ""}{dxy.toFixed(2)}
            </span>
          )}
          {credit != null && (
            <span className="font-num">
              <span className="text-on-surface-variant/40">HY spread </span>
              {credit >= 0 ? "+" : ""}{credit.toFixed(2)}
            </span>
          )}
        </div>
      )}

      {/* Key markets + stale indicator */}
      {!!(data.key_markets && data.key_markets.length > 0) && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/50">
            Confirm / challenge
          </span>
          {data.key_markets.map((m) => (
            <span
              key={m}
              className="font-num text-[10px] text-on-surface/80 bg-surface-container-highest rounded px-1.5 py-0.5"
            >
              {m}
            </span>
          ))}
          {data.stale && (
            <span className="text-[9px] text-on-surface-variant/50 italic">
              context partial
            </span>
          )}
        </div>
      )}
    </section>
  );
}

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
          <AnalogCard
            key={`${a.headline}-${a.event_date ?? "no-date"}-${i}`}
            analog={a}
            rank={i + 1}
          />
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

// Memoised so that selecting one card cannot trigger other cards to
// re-render with leaked props.  Each card is a pure function of its
// own ticker dict + selected flag — the equality check below pins
// rendering to identity of those scalar fields, never to the parent
// closure.
const TickerCard = memo(function TickerCard({
  ticker, selected, onToggle,
}: { ticker: Ticker; selected: boolean; onToggle: () => void }) {
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
}, (prev, next) => (
  prev.selected === next.selected
  && prev.ticker.symbol === next.ticker.symbol
  && prev.ticker.label === next.ticker.label
  && prev.ticker.return_5d === next.ticker.return_5d
  && prev.ticker.return_20d === next.ticker.return_20d
  && prev.ticker.direction_tag === next.ticker.direction_tag
  && prev.ticker.spark === next.ticker.spark
));

function MarketSection({ tickers, eventDate }: { tickers: Ticker[]; eventDate?: string }) {
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const selectedTicker = tickers.find((t) => t.symbol === selectedSymbol);
  if (tickers.length === 0) return <p className="text-xs text-on-surface-variant text-center py-4">No market data returned.</p>;
  const withDir = tickers.filter((t) => t.direction_tag != null);
  const supportCount = withDir.filter(isSupporting).length;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {tickers.map((t, i) => (
          // Compound key — survives any backend regression that
          // accidentally emits two ticker dicts with the same symbol
          // (which would otherwise cause React to reconcile them into
          // a single card and visibly leak data between cards).
          <TickerCard
            key={`${t.symbol}-${i}`}
            ticker={t}
            selected={selectedSymbol === t.symbol}
            onToggle={() => setSelectedSymbol((s) => (s === t.symbol ? null : t.symbol))}
          />
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
  /** When set, the backend will load this event by primary key instead of
   *  doing a headline-string lookup — prevents near-duplicate stories from
   *  cross-routing.  Supplied by Market Overview card clicks. */
  initialEventId?: number;
  onHeadlineConsumed?: () => void;
  onBack?: () => void;
}

type Phase = "idle" | "classify" | "analysis" | "market" | "complete";

export function AnalysisView({ initialHeadline, initialContext, initialEventId, onHeadlineConsumed, onBack }: AnalysisViewProps) {
  const [headline, setHeadline] = useState("");
  const [eventDate] = useState("");
  const contextRef = useRef<string | undefined>(initialContext);
  const eventDateRef = useRef(eventDate);
  eventDateRef.current = eventDate;
  // Keep track of the pending event_id across the async submit cycle.
  const pendingEventIdRef = useRef<number | undefined>(initialEventId);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const loading = phase !== "idle" && phase !== "complete";

  useEffect(() => () => { abortRef.current?.abort(); }, []);

  const submit = useCallback(async (h?: string, eventId?: number) => {
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
        {
          headline: text,
          event_date: eventDateRef.current || undefined,
          event_context: contextRef.current || undefined,
          event_id: eventId ?? pendingEventIdRef.current,
        },
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
      pendingEventIdRef.current = initialEventId;
      onHeadlineConsumed?.();
      submit(initialHeadline, initialEventId);
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
      {/* Sticky back-nav row.  Sits directly under the (also sticky)
          TopBar (`top-14`) so the user can return to Market Overview
          from anywhere in a long analysis without scrolling back to
          the page top.  Negative margins extend the bar to the
          workspace padding edges so its backdrop reaches full width.
      */}
      {onBack && (
        <div className="sticky top-14 z-20 -mx-3 -mt-3 mb-4 px-3 py-2 bg-background/85 backdrop-blur-sm md:-mx-5 md:-mt-4 md:px-5">
          <button onClick={onBack} className="group flex items-center gap-2 text-on-surface-variant hover:text-primary transition-colors">
            <span className="w-8 h-8 flex items-center justify-center rounded-lg bg-surface-container-highest group-hover:bg-surface-bright transition-colors">
              <ArrowLeft className="h-4 w-4" />
            </span>
            <span className="text-[10px] font-bold uppercase tracking-[0.15em]">Market Overview</span>
          </button>
        </div>
      )}

      {/* ── TOP AREA ── */}
      <div className="mb-8">

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

              {/* Real Yield / Breakeven Context */}
              {result.analysis.real_yield_context && result.analysis.real_yield_context.thesis && result.analysis.real_yield_context.thesis !== "none" && (
                <RealYieldContextBlock data={result.analysis.real_yield_context} />
              )}

              {/* Policy Constraint Engine */}
              {result.analysis.policy_constraint && result.analysis.policy_constraint.binding && (
                <PolicyConstraintBlock data={result.analysis.policy_constraint} />
              )}

              {/* Real vs Nominal Shock Decomposition */}
              {result.analysis.shock_decomposition && result.analysis.shock_decomposition.primary && (
                <ShockDecompositionBlock data={result.analysis.shock_decomposition} />
              )}

              {/* Reaction Function Divergence */}
              {result.analysis.reaction_function_divergence && result.analysis.reaction_function_divergence.divergence && (
                <ReactionFunctionDivergenceBlock data={result.analysis.reaction_function_divergence} />
              )}

              {/* Surprise vs Anticipation Decomposition */}
              {result.analysis.surprise_vs_anticipation && result.analysis.surprise_vs_anticipation.regime && (
                <SurpriseVsAnticipationBlock data={result.analysis.surprise_vs_anticipation} />
              )}

              {/* Terms-of-Trade / External Vulnerability */}
              {result.analysis.terms_of_trade && result.analysis.terms_of_trade.dominant_channel && (
                <TermsOfTradeBlock data={result.analysis.terms_of_trade} />
              )}

              {/* Current Account + FX Reserve Stress */}
              {result.analysis.reserve_stress && result.analysis.reserve_stress.dominant_channel && (
                <ReserveStressBlock data={result.analysis.reserve_stress} />
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
