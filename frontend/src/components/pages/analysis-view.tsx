import { useState, useEffect, useCallback, useRef, memo } from "react";
import { useQuery } from "@tanstack/react-query";
import { qk } from "@/lib/queryKeys";
import { Skeleton } from "@/components/ui/skeleton";
import { Sparkline } from "@/components/ui/sparkline";
import { MarketBackdropStrip } from "@/components/ui/market-backdrop-strip";
import { TickerDetailPanel } from "@/components/ui/ticker-detail-panel";
import { getStepLabel, isAccentStep } from "@/components/ui/transmission-chain";
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
  Copy,
  ClipboardCheck,
  FileText,
  Download,
  RefreshCw,
  Clock,
  MessageSquare,
} from "lucide-react";
import { api, type AnalyzeResponse, type Confidence, type Ticker, type AnalysisDetail, type CurrencyChannel, type PolicySensitivity, type InventoryContext, type RealYieldContext, type PolicyConstraint, type ShockDecomposition, type ReactionFunctionDivergence, type SurpriseVsAnticipation, type TermsOfTrade, type TermsOfTradeExposure, type ReserveStress, type ReserveStressVulnerable, type ReserveStressInsulated, type NarrativeDivergence, type RoleSignal, type HistoricalAnalog, type AnalogMatchDimension, type RevisitSnapshot, type ConfidenceCalibration, type CrossAssetConfirmation, type CreditTransmission, type HorizonCheckpoints, type HorizonCheckpoint, type SectorPassthrough, type SectorPassthroughEntry, type MechanismFamily, type ExpectedChannel, type Counterforce, type SubstitutionBarrier, type EventMacroReleaseContext, type EventPolicyTimingContext, type EventCountryVulnerabilityContext, type PolicyTimingStatus, type VulnerabilityTier, type CommodityTier } from "@/lib/api";
import { deriveAllHorizons, deriveTrajectory, type HorizonSummary, type ThesisTrajectory } from "@/lib/revisit-derivation";
import "@/styles/analyze-canvas.css";
import { cn } from "@/lib/utils";
import { pct } from "@/lib/ticker-utils";
import { formatMemo, formatBlurb, formatMemoMarkdown } from "@/lib/format-memo";
import { EvidenceQualityStrip } from "@/components/ui/evidence-quality-strip";
import { EnginePhaseSummary } from "@/components/ui/engine-phase-summary";
import { MarketValidationStatus } from "@/components/ui/market-validation-status";
import { EventStudyCard } from "@/components/ui/event-study-card";
import { deriveDegradedNotice } from "@/components/ui/degraded-data-notice";
import { DegradedBanner } from "@/components/ui/degraded-banner";
import { MARKET_REACTION_LABEL, MARKET_REACTION_SUBLABEL, VALIDATION_V2_SCOPE_CAVEAT, VALIDATION_V2_NOT_CLAIMED } from "@/lib/claim-copy";

/*
  Tonal hierarchy (from Stitch reference):
    Page background:   #0a0a0f  (body / main)
    Big section card:  #13131a  (bg-surface-container-low)
    Inner card:        #242533  (bg-surface-container-highest)
*/

// ---------------------------------------------------------------------------
// Confidence — three clearly distinct muted colours
// ---------------------------------------------------------------------------

const CONFIDENCE: Record<Confidence, {
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
const SECTION_CARD = "bg-surface-container-low rounded-lg";
// Inner card (bg-surface-container-highest)
const INNER_CARD = "bg-surface-container-highest rounded-md";

// Section lead — Direction-C rhythm: a hairline top rule, a citrine mono
// number, a display-serif title, and quiet serif subcopy.  Anchors each
// numbered section so the page reads as one numbered narrative.
function SectionLead({ num, title, sub }: { num: string; title: string; sub?: string }) {
  return (
    <div className="mb-3">
      <div className="flex items-baseline gap-2.5 border-t border-[color:var(--so-rule-hi)] pt-3">
        <span className="font-mono text-[12px] italic tabular-nums tracking-wide text-[var(--so-citrine)]">
          {num} ·
        </span>
        <h3 className="font-[family-name:var(--so-display)] text-[21px] font-normal leading-tight tracking-[-0.01em] text-[var(--so-ink-0)]">
          {title}
        </h3>
      </div>
      {sub && (
        <p className="mt-1.5 font-[family-name:var(--so-serif)] text-[12.5px] font-light italic leading-snug text-[var(--so-ink-3)]">
          {sub}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="az-card-title mb-4 flex items-center gap-2">
      <span className="h-3 w-0.5 rounded-full bg-[var(--so-citrine)]" />
      {children}
    </h4>
  );
}

// ---------------------------------------------------------------------------
// Transmission — Direction-C mono hop-chain (`az-hop`).  Numbered nodes,
// hairline vertical connectors, citrine chrome on the markers, serif step
// text.  Reuses the tested pure helpers (getStepLabel / isAccentStep) and
// the existing string[] step data — no actor/channel fields are invented.
// Analyze-local so the shared transmission-chain component (and Market
// Movers) stays untouched.
// ---------------------------------------------------------------------------

function AzTransmissionChain({ steps }: { steps: string[] }) {
  if (!steps || steps.length === 0) return null;
  return (
    <div>
      {steps.map((step, i) => {
        const label = getStepLabel(i, steps.length);
        const accent = isAccentStep(i, steps.length);
        const isLast = i === steps.length - 1;
        return (
          <div key={i} className="relative grid grid-cols-[28px_1fr] gap-4 pb-4 last:pb-0">
            <div className="relative flex justify-center">
              <span
                className={cn(
                  "z-10 grid h-7 w-7 place-items-center rounded-full border bg-[var(--so-bg-1)] font-mono text-[10px] tabular-nums",
                  accent
                    ? "border-[color:rgba(212,179,67,0.45)] text-[var(--so-citrine)]"
                    : "border-[color:var(--so-rule-hi)] text-[var(--so-ink-3)]",
                )}
              >
                {String(i + 1).padStart(2, "0")}
              </span>
              {!isLast && (
                <span className="absolute left-1/2 top-7 -bottom-4 w-px -translate-x-1/2 bg-[color:var(--so-rule-hi)]" />
              )}
            </div>
            <div className="min-w-0 pt-1">
              <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--so-ink-3)]">
                {label}
              </p>
              <p className="font-[family-name:var(--so-serif)] text-[13.5px] font-light leading-relaxed text-[var(--so-ink-1)]">
                {step}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Macro Backdrop — compact regime/rates summary that was fed into the LLM
// ---------------------------------------------------------------------------

const VALIDATION_STATUS_META: Record<string, { label: string; dot: string; text: string; bg: string }> = {
  validated:    { label: "Validated",    dot: "bg-[#6ec6a5]", text: "text-[#6ec6a5]", bg: "bg-[#6ec6a5]/8" },
  contradicted: { label: "Contradicted", dot: "bg-[#ee7d77]", text: "text-[#ee7d77]", bg: "bg-[#ee7d77]/10" },
  unresolved:   { label: "Unresolved",   dot: "bg-[#a89f91]", text: "text-[#a89f91]", bg: "bg-[#a89f91]/8" },
  pending:      { label: "Pending",      dot: "bg-[var(--so-slate)]", text: "text-[var(--so-slate)]", bg: "bg-[rgba(122,134,148,0.08)]" },
};

function _compactPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${Math.round(normalized)}%`;
}

function _labelizeToken(value: string | null | undefined, fallback = "Unknown"): string {
  if (!value) return fallback;
  return value
    .replace(/_/g, " ")
    .replace(/(?:^|\s)\w/g, (c) => c.toUpperCase());
}

export function ValidationStatusCard({ block }: { block: NonNullable<AnalyzeResponse["validation_status_v2"]> }) {
  const meta = VALIDATION_STATUS_META[block.status] ?? VALIDATION_STATUS_META.unresolved!;
  const counts = block.counts ?? {};
  const directional = counts.directional ?? 0;
  const supporting = counts.supporting ?? 0;
  const contradicting = counts.contradicting ?? 0;
  const total = counts.total_tickers ?? 0;

  return (
    <section className={cn(SECTION_CARD, "p-5")}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="az-card-title mb-2">Validation status</p>
          <div className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1", meta.bg)}>
            <span className={cn("h-1.5 w-1.5 rounded-full", meta.dot)} />
            <span className={cn("text-[10px] font-bold uppercase tracking-[0.14em]", meta.text)}>
              {meta.label}
            </span>
          </div>
        </div>
        <div className="text-right">
          <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--so-ink-3)]">
            Support ratio
          </p>
          <p className="font-[family-name:var(--so-display)] text-[28px] font-normal leading-none tabular-nums text-[var(--so-jade-ink)]">
            {_compactPercent(block.ratio)}
          </p>
        </div>
      </div>

      {/* Claim boundary, kept WITH the verdict (R2A): the scope caveat and an
          explicit "Not claimed" line sit directly under the verdict + ratio so
          a reader sees what the scored verdict does and does not assert without
          scrolling to a footer. */}
      <div className="mb-4 border-t border-[color:var(--so-rule)] pt-3">
        <p className="font-[family-name:var(--so-serif)] text-[11px] font-light italic leading-relaxed text-[var(--so-ink-3)]">
          {VALIDATION_V2_SCOPE_CAVEAT}
        </p>
        <p className="mt-1.5 font-mono text-[10px] tracking-[0.02em] text-[var(--so-ink-3)]">
          {VALIDATION_V2_NOT_CLAIMED}
        </p>
      </div>

      <p className="mb-4 font-[family-name:var(--so-serif)] text-[12.5px] font-light italic leading-relaxed text-[var(--so-ink-2)]">
        {block.reason || "No validation reason available."}
      </p>

      <div className="grid grid-cols-3 gap-2 border-t border-[color:var(--so-rule)] pt-3">
        {([
          ["Directional", directional, "text-[var(--so-ink-0)]"],
          ["Supports", supporting, "text-[var(--so-jade-ink)]"],
          ["Contradicts", contradicting, "text-[var(--so-rust-ink)]"],
        ] as const).map(([label, value, cls]) => (
          <div key={label}>
            <p className="font-mono text-[8.5px] uppercase tracking-[0.1em] text-[var(--so-ink-3)]">
              {label}
            </p>
            <p className={cn("font-mono text-[16px] font-semibold tabular-nums", cls)}>{value}</p>
          </div>
        ))}
      </div>

      <p className="mt-3 font-mono text-[9.5px] uppercase tracking-[0.08em] text-[var(--so-ink-3)]">
        {total} ticker{total === 1 ? "" : "s"} checked
        {block.event_age_days != null ? ` · ${block.event_age_days}d since event` : ""}
      </p>
    </section>
  );
}

function ReactionProfileCard({ block }: { block: NonNullable<AnalyzeResponse["reaction_profile_v1"]> }) {
  const tickers = block.tickers ?? [];
  const displayTickers = tickers.slice(0, 4);
  const isUnscorable = !block.available;

  return (
    <section className={cn(SECTION_CARD, "p-5")}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="az-card-title mb-2">Reaction profile</p>
          <div
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1",
              isUnscorable ? "bg-[rgba(122,134,148,0.10)]" : "bg-[rgba(152,194,173,0.10)]",
            )}
          >
            <span className={cn("h-1.5 w-1.5 rounded-full", isUnscorable ? "bg-[var(--so-slate)]" : "bg-[var(--so-jade-ink)]")} />
            <span
              className={cn(
                "text-[10px] font-bold uppercase tracking-[0.14em]",
                isUnscorable ? "text-[var(--so-slate)]" : "text-[var(--so-jade-ink)]",
              )}
            >
              {isUnscorable ? "Unscorable" : "Available"}
            </span>
          </div>
        </div>
        <div className="text-right">
          <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--so-ink-3)]">
            Tickers
          </p>
          <p className="font-[family-name:var(--so-display)] text-[24px] font-normal leading-none tabular-nums text-[var(--so-ink-0)]">
            {block.n_tickers ?? tickers.length}
          </p>
        </div>
      </div>

      <p className="mb-4 font-[family-name:var(--so-serif)] text-[12.5px] font-light italic leading-relaxed text-[var(--so-ink-2)]">
        {block.reason || (isUnscorable ? "Not enough stored price history to score the reaction profile." : "Reaction profile computed.")}
      </p>

      {displayTickers.length > 0 ? (
        <div>
          {displayTickers.map((ticker, index) => {
            const basis = ticker.reaction_profile_basis ?? "unscorable";
            const status =
              ticker.fade_or_hold_label_20d
              ?? ticker.fade_or_hold_label_5d
              ?? ticker.fade_or_hold_label_60d
              ?? (basis === "unscorable" ? "insufficient" : null);
            // Basis: forward-anchored reads jade, same-day fallback amber,
            // stale/unscorable slate.  Hold reads jade, fade amber, reverse
            // rust — a tape read, not a directional verdict.
            const basisTone = basis.includes("forward")
              ? "text-[var(--so-jade-ink)]"
              : basis.includes("fallback") ? "text-[var(--so-amber)]" : "text-[var(--so-ink-3)]";
            const statusTone = status === "hold"
              ? "text-[var(--so-jade-ink)]"
              : status === "fade" ? "text-[var(--so-amber)]"
              : status === "reverse" ? "text-[var(--so-rust-ink)]" : "text-[var(--so-ink-3)]";
            return (
              <div
                key={`${ticker.symbol ?? "ticker"}-${index}`}
                className="grid grid-cols-[58px_1fr_auto] items-baseline gap-3 border-b border-[color:var(--so-rule)] py-2 last:border-b-0"
              >
                <span className="font-mono text-[12px] text-[var(--so-ink-0)]">{ticker.symbol || "—"}</span>
                <span className={cn("min-w-0 truncate font-mono text-[9.5px] uppercase tracking-[0.06em]", basisTone)}>
                  {_labelizeToken(basis, "no basis")}
                </span>
                <span className={cn("shrink-0 font-mono text-[10px] uppercase tracking-[0.1em]", statusTone)}>
                  {_labelizeToken(status, "—")}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <div className={cn(INNER_CARD, "px-3 py-2 text-[11px] text-on-surface-variant/60")}>
          No market tickers were stored for this event, so there is no per-ticker reaction profile.
        </div>
      )}
    </section>
  );
}

function ValidationReactionPanel({ result, eventId }: { result: AnalyzeResponse; eventId?: number }) {
  // Read-only fetch of the gated event-study payload from the verified
  // standalone route.  Enabled only for persisted events; the hook runs
  // unconditionally (gated via `enabled`) so hook order stays stable.
  const { data: eventStudy } = useQuery({
    queryKey: qk.eventStudy(eventId ?? 0),
    queryFn: () => api.getEventStudy(eventId as number),
    enabled: typeof eventId === "number" && eventId > 0,
    staleTime: 300_000,
  });

  const validationBlock = result.validation_status_v2 ?? result.analysis?.validation_status_v2;
  const reactionBlock = result.reaction_profile_v1 ?? result.analysis?.reaction_profile_v1;

  if (!validationBlock && !reactionBlock && !eventStudy) return null;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {validationBlock && (
        <ValidationStatusCard block={validationBlock} />
      )}
      {reactionBlock && (
        <ReactionProfileCard block={reactionBlock} />
      )}
      {eventStudy && (
        <EventStudyCard block={eventStudy} />
      )}
    </div>
  );
}

function MacroBackdropBlock({ analysis }: { analysis: AnalysisDetail }) {
  const ps  = analysis.policy_sensitivity;
  const ryc = analysis.real_yield_context;
  const sd  = analysis.shock_decomposition;

  const regime      = ps?.regime;
  const stance      = ps?.stance;
  const ryAlignment = ryc?.alignment && ryc.alignment !== "stale" ? ryc.alignment : undefined;
  const shockLabel  = sd?.primary_label && sd.primary !== "none" ? sd.primary_label : undefined;

  if (!regime && !stance && !ryAlignment && !shockLabel) return null;

  const formatRegime = (r: string) =>
    r.replace(/_/g, " ").replace(/(?:^|\s)\w/g, (c) => c.toUpperCase());

  const stanceColor =
    stance === "reinforced" ? "text-[#6ec6a5]" :
    stance === "fighting"   ? "text-[#ee7d77]" :
    "text-on-surface-variant/60";

  const stanceLabel =
    stance === "reinforced" ? "Reinforced" :
    stance === "fighting"   ? "Fighting CB" :
    stance === "neutral"    ? "Neutral" :
    stance ?? "";

  const ryColor =
    ryAlignment === "confirm"  ? "text-[#6ec6a5]" :
    ryAlignment === "tension"  ? "text-[#ee7d77]" :
    "text-on-surface-variant/60";

  const ryLabel =
    ryAlignment === "confirm"  ? "Confirming" :
    ryAlignment === "tension"  ? "In tension" :
    ryAlignment === "neutral"  ? "Neutral" :
    "";

  type Chip = { key: string; label: string; value: string; valueClass: string };
  const chips: Chip[] = [];
  if (regime)      chips.push({ key: "regime",  label: "Rates Regime",  value: formatRegime(regime), valueClass: "text-on-surface-variant/80" });
  if (stance)      chips.push({ key: "stance",  label: "CB Stance",     value: stanceLabel,           valueClass: stanceColor });
  if (ryAlignment) chips.push({ key: "ry",      label: "Real Yield",    value: ryLabel,               valueClass: ryColor });
  if (shockLabel)  chips.push({ key: "shock",   label: "Shock Channel", value: shockLabel,            valueClass: "text-on-surface-variant/80" });

  return (
    <section className={cn(SECTION_CARD, "px-6 py-4")}>
      <p className="section-kicker mb-3">Macro Backdrop at Analysis</p>
      <div className="flex flex-wrap gap-2">
        {chips.map(({ key, label, value, valueClass }) => (
          <div key={key} className={cn(INNER_CARD, "px-3 py-2 flex flex-col gap-0.5 min-w-[90px]")}>
            <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/35">{label}</span>
            <span className={cn("text-[11px] font-medium leading-snug", valueClass)}>{value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}


// ---------------------------------------------------------------------------
// Macro Release Context — compact additive strip when the event maps to a
// known macro release (CPI / PPI / NFP / Unemployment / PCE).  Mirrors the
// headline-surface badge vocabulary so the same release reads consistently
// across both pages.  Returns null when the block is empty — no placeholder
// chrome for unmapped events.
// ---------------------------------------------------------------------------

const _MACRO_LABEL_TEXT: Record<string, string> = {
  beat:    "Beat",
  miss:    "Miss",
  in_line: "In line",
  unknown: "Print",
};

const _MACRO_LABEL_COLOR: Record<string, string> = {
  beat:    "text-[#93d1d3]",
  miss:    "text-[#ee7d77]",
  in_line: "text-on-surface-variant/65",
  unknown: "text-on-surface-variant/60",
};

function _fmtMacroNum(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1000) return value.toLocaleString();
  if (Number.isInteger(value)) return value.toString();
  return value.toFixed(2);
}

export function MacroReleaseContextBlock({ data }: { data: EventMacroReleaseContext }) {
  if (!data?.release_key) return null;

  const label = data.surprise_label ?? "unknown";
  const labelText = _MACRO_LABEL_TEXT[label] ?? "Print";
  const labelColor = _MACRO_LABEL_COLOR[label] ?? _MACRO_LABEL_COLOR.unknown;

  const hasRevision =
    data.revised_prior !== null && data.revised_prior !== undefined
    && data.revised_prior !== data.prior;

  const cells: { key: string; label: string; value: string; cls?: string }[] = [
    { key: "actual",    label: "Actual",    value: _fmtMacroNum(data.actual),    cls: "text-foreground" },
    { key: "consensus", label: "Consensus", value: _fmtMacroNum(data.consensus) },
    { key: "prior",     label: "Prior",     value: _fmtMacroNum(data.prior) },
  ];

  return (
    <section className={cn(SECTION_CARD, "px-6 py-3")}>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        {/* Left: release key + timestamp + source (secondary metadata) */}
        <div className="flex flex-col gap-0.5 min-w-[140px]">
          <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/35">
            Macro Release
          </span>
          <span className="text-[12px] font-semibold tabular-nums text-foreground/85 leading-snug">
            {data.release_key}
          </span>
          {(data.release_time || data.source) && (
            <span className="text-[10px] text-on-surface-variant/55 tabular-nums">
              {data.release_time ? data.release_time.slice(0, 16).replace("T", " ") : ""}
              {data.release_time && data.source ? " · " : ""}
              {data.source}
            </span>
          )}
        </div>

        {/* Middle: surprise label — primary read, prominent */}
        <div className="flex items-baseline gap-2">
          <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/35">
            Surprise
          </span>
          <span className={cn("text-[14px] font-bold tracking-tight", labelColor)}>
            {labelText}
          </span>
        </div>

        {/* Right: numbers — tabular, dense */}
        <div className="flex items-center gap-3 ml-auto">
          {cells.map((cell) => (
            <div key={cell.key} className="flex flex-col gap-0.5 min-w-[60px]">
              <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/35">
                {cell.label}
              </span>
              <span className={cn("text-[12px] font-num tabular-nums font-medium leading-snug",
                cell.cls ?? "text-foreground/75")}>
                {cell.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Revision line — visible but quiet, below the main read */}
      {hasRevision && (
        <div className="mt-2 pt-2 border-t border-border/15 flex items-center gap-2 text-[10px] text-on-surface-variant/60">
          <span className="uppercase tracking-[0.15em] font-bold text-on-surface-variant/40">Revision</span>
          <span className="tabular-nums">
            Prior {_fmtMacroNum(data.prior)} → {_fmtMacroNum(data.revised_prior)}
          </span>
        </div>
      )}
    </section>
  );
}


// ---------------------------------------------------------------------------
// Policy Timing Context — compact secondary strip when the event maps to
// a tracked policy (tariff / sanction / rate decision / regulation).
// Mirrors the headline-surface strip vocabulary (announced / effective /
// under_review / expired) so the same policy reads consistently across
// both pages.  Renders nothing when policy_key is null — no placeholder.
// ---------------------------------------------------------------------------

const _POLICY_STATUS_LABEL: Record<PolicyTimingStatus, string> = {
  announced:    "Announced",
  effective:    "Effective",
  under_review: "Under Review",
  expired:      "Expired",
};

// Colour discipline — matches the headlines-page PolicyTimingStrip so
// the same status reads identically on both surfaces.
const _POLICY_STATUS_STYLE: Record<PolicyTimingStatus, {
  border: string; bg: string; text: string; dot: string;
}> = {
  announced: {
    border: "border-[#93d1d3]/35",
    bg:     "bg-[#93d1d3]/10",
    text:   "text-[#93d1d3]",
    dot:    "bg-[#93d1d3]",
  },
  effective: {
    border: "border-[#ee7d77]/35",
    bg:     "bg-[#ee7d77]/10",
    text:   "text-[#ee7d77]",
    dot:    "bg-[#ee7d77]",
  },
  under_review: {
    border: "border-[#facc15]/30",
    bg:     "bg-[#facc15]/8",
    text:   "text-[#facc15]/85",
    dot:    "bg-[#facc15]/80",
  },
  expired: {
    border: "border-border/40",
    bg:     "bg-secondary/40",
    text:   "text-on-surface-variant/55",
    dot:    "bg-on-surface-variant/40",
  },
};

export function PolicyTimingContextBlock({
  data,
}: {
  data: EventPolicyTimingContext;
}) {
  // Canonical empty shape: policy_key === null.  Render nothing so the
  // page stays calm on unmapped events — no placeholder chrome.
  if (!data?.policy_key) return null;

  const status = (data.status ?? "announced") as PolicyTimingStatus;
  const style = _POLICY_STATUS_STYLE[status] ?? _POLICY_STATUS_STYLE.announced;
  const label = _POLICY_STATUS_LABEL[status] ?? status;

  const dateCells: { key: string; label: string; value: string }[] = [
    { key: "announced", label: "Announced", value: data.announced_date ?? "—" },
    { key: "effective", label: "Effective", value: data.effective_date ?? "—" },
    { key: "review",    label: "Review",    value: data.review_date    ?? "—" },
  ];

  return (
    <section className={cn(SECTION_CARD, "px-6 py-3")}>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        {/* Left: kicker + policy key + source — secondary metadata */}
        <div className="flex flex-col gap-0.5 min-w-[160px]">
          <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/35">
            Policy Timing
          </span>
          <span className="text-[12px] font-semibold text-foreground/85 leading-snug font-num tabular-nums break-all">
            {data.policy_key}
          </span>
          {data.source && (
            <span className="text-[10px] text-on-surface-variant/55">
              {data.source}
            </span>
          )}
        </div>

        {/* Middle: status pill — the primary at-a-glance read */}
        <div className="flex items-center">
          <span className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2 py-[2px]",
            "text-[9px] font-bold uppercase tracking-wider",
            style.border, style.bg, style.text,
          )}>
            <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", style.dot)} />
            <span>{label}</span>
          </span>
        </div>

        {/* Right: three dates — tabular, dense */}
        <div className="flex items-center gap-3 ml-auto">
          {dateCells.map((cell) => (
            <div key={cell.key} className="flex flex-col gap-0.5 min-w-[76px]">
              <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/35">
                {cell.label}
              </span>
              <span className="text-[11px] font-num tabular-nums font-medium text-foreground/75 leading-snug">
                {cell.value}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}


// ---------------------------------------------------------------------------
// Country Vulnerability Context — compact secondary strip when the event
// resolves to a country profiled in the backend country_backdrop
// fixture.  Renders nothing when country is null — unprofiled events
// keep the page byte-stable.
// ---------------------------------------------------------------------------

const _VULN_TIER_LABEL: Record<VulnerabilityTier, string> = {
  resilient:  "Resilient",
  moderate:   "Moderate",
  vulnerable: "Vulnerable",
  fragile:    "Fragile",
};

const _VULN_TIER_TEXT: Record<VulnerabilityTier, string> = {
  resilient:  "text-[#93d1d3]",
  moderate:   "text-on-surface-variant/75",
  vulnerable: "text-[#facc15]/85",
  fragile:    "text-[#ee7d77]",
};

const _COMMODITY_TIER_LABEL: Record<CommodityTier, string> = {
  low:      "Low",
  moderate: "Moderate",
  high:     "High",
  dominant: "Dominant",
};

const _COMMODITY_TIER_TEXT: Record<CommodityTier, string> = {
  low:      "text-on-surface-variant/55",
  moderate: "text-on-surface-variant/75",
  high:     "text-foreground/80",
  dominant: "text-[#93d1d3]",
};

export function CountryVulnerabilityContextBlock({
  data,
}: {
  data: EventCountryVulnerabilityContext;
}) {
  // Canonical empty shape: country === null.  Render nothing so the
  // page stays calm on events that don't resolve to a profiled country.
  if (!data?.country) return null;

  const overall = data.overall_vulnerability;
  const overallLabel = overall
    ? (_VULN_TIER_LABEL[overall] ?? overall)
    : "—";
  const overallColor = overall
    ? (_VULN_TIER_TEXT[overall] ?? "text-foreground/80")
    : "text-on-surface-variant/55";

  const tierCells: {
    key: string; label: string; value: string; cls: string;
  }[] = [
    {
      key:   "external",
      label: "External Balance",
      value: data.external_balance_risk
        ? (_VULN_TIER_LABEL[data.external_balance_risk] ?? data.external_balance_risk)
        : "—",
      cls:   data.external_balance_risk
        ? (_VULN_TIER_TEXT[data.external_balance_risk] ?? "text-foreground/80")
        : "text-on-surface-variant/55",
    },
    {
      key:   "import",
      label: "Import Shock",
      value: data.import_shock_risk
        ? (_VULN_TIER_LABEL[data.import_shock_risk] ?? data.import_shock_risk)
        : "—",
      cls:   data.import_shock_risk
        ? (_VULN_TIER_TEXT[data.import_shock_risk] ?? "text-foreground/80")
        : "text-on-surface-variant/55",
    },
    {
      key:   "commodity",
      label: "Commodity Dep.",
      value: data.commodity_dependence
        ? (_COMMODITY_TIER_LABEL[data.commodity_dependence] ?? data.commodity_dependence)
        : "—",
      cls:   data.commodity_dependence
        ? (_COMMODITY_TIER_TEXT[data.commodity_dependence] ?? "text-foreground/80")
        : "text-on-surface-variant/55",
    },
  ];

  return (
    <section className={cn(SECTION_CARD, "px-6 py-3")}>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        {/* Left: kicker + country + overall vulnerability — primary read */}
        <div className="flex flex-col gap-0.5 min-w-[140px]">
          <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/35">
            Country Vulnerability
          </span>
          <span className="text-[12px] font-semibold text-foreground/85 leading-snug">
            {data.country}
          </span>
          <span className={cn("text-[11px] font-medium leading-snug", overallColor)}>
            Overall: {overallLabel}
          </span>
        </div>

        {/* Right: three risk cells — tabular, dense */}
        <div className="flex items-center gap-3 ml-auto">
          {tierCells.map((cell) => (
            <div key={cell.key} className="flex flex-col gap-0.5 min-w-[100px]">
              <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/35">
                {cell.label}
              </span>
              <span className={cn(
                "text-[11px] font-medium leading-snug",
                cell.cls,
              )}>
                {cell.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Rationale line — quiet, below the main read */}
      {data.rationale && data.rationale.trim().length > 0 && (
        <div className="mt-2 pt-2 border-t border-border/15 text-[10px] text-on-surface-variant/60 leading-snug">
          <span className="uppercase tracking-[0.15em] font-bold text-on-surface-variant/40 mr-2">
            Rationale
          </span>
          <span>{data.rationale}</span>
        </div>
      )}
    </section>
  );
}


// ---------------------------------------------------------------------------
// Research Output memo — collapsible copy-friendly text block
// ---------------------------------------------------------------------------

function ResearchMemoBlock({ result }: { result: AnalyzeResponse }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [blurbCopied, setBlurbCopied] = useState(false);

  const memo = formatMemo(result);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(memo).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const handleBlurb = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(formatBlurb(result)).then(() => {
      setBlurbCopied(true);
      setTimeout(() => setBlurbCopied(false), 2000);
    });
  };

  const _slug = () =>
    result.headline
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "")
      .slice(0, 48);

  const handleDownload = (e: React.MouseEvent) => {
    e.stopPropagation();
    const blob = new Blob([memo], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `second-order-${_slug()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDownloadMd = (e: React.MouseEvent) => {
    e.stopPropagation();
    const blob = new Blob([formatMemoMarkdown(result)], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `second-order-${_slug()}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className={cn(SECTION_CARD, "overflow-hidden")}>
      <div
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-6 py-4 text-left group cursor-pointer"
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && setOpen((v) => !v)}
      >
        <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant flex items-center gap-2">
          <FileText className="h-3.5 w-3.5 text-primary/60" />
          Research Output
        </span>
        <span className="flex items-center gap-2">
          <button
            onClick={handleDownload}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium transition-colors bg-surface-container-highest text-on-surface-variant/60 hover:text-on-surface-variant"
          >
            <Download className="h-3 w-3" />
            .txt
          </button>
          <button
            onClick={handleDownloadMd}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium transition-colors bg-surface-container-highest text-on-surface-variant/60 hover:text-on-surface-variant"
          >
            <Download className="h-3 w-3" />
            .md
          </button>
          <button
            onClick={handleBlurb}
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium transition-colors",
              blurbCopied
                ? "bg-primary/15 text-primary"
                : "bg-surface-container-highest text-on-surface-variant/60 hover:text-on-surface-variant",
            )}
          >
            {blurbCopied ? <ClipboardCheck className="h-3 w-3" /> : <MessageSquare className="h-3 w-3" />}
            {blurbCopied ? "Copied" : "Blurb"}
          </button>
          <button
            onClick={handleCopy}
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium transition-colors",
              copied
                ? "bg-primary/15 text-primary"
                : "bg-surface-container-highest text-on-surface-variant/60 hover:text-on-surface-variant",
            )}
          >
            {copied ? <ClipboardCheck className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            {copied ? "Copied" : "Copy"}
          </button>
          <ChevronDown
            className={cn(
              "h-3.5 w-3.5 text-on-surface-variant/40 transition-transform",
              open && "rotate-180",
            )}
          />
        </span>
      </div>
      {open && (
        <div className="px-6 pb-5">
          <div className={cn(INNER_CARD, "p-4 overflow-x-auto")}>
            <pre className="font-mono text-[11px] leading-relaxed text-on-surface-variant/80 whitespace-pre-wrap">
              {memo}
            </pre>
          </div>
        </div>
      )}
    </section>
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
  const style = (STANCE_STYLE[data.stance] ?? STANCE_STYLE.neutral)!;
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
  // comfortable / calm / supportive reads MUTED JADE, not bright teal —
  // citrine stays chrome-only and teal stays a market-return colour.
  tight:       { icon: "▲", color: "text-error-dim", bg: "bg-error-dim/8" },
  comfortable: { icon: "▼", color: "text-[var(--so-jade-ink)]", bg: "bg-[rgba(152,194,173,0.07)]" },
  neutral:     { icon: "●", color: "text-on-surface-variant", bg: "bg-surface-container-highest" },
};

function InventoryContextBlock({ data }: { data: InventoryContext }) {
  if (!data.status || !data.explanation) return null;
  const style = (INV_STYLE[data.status] ?? INV_STYLE.neutral)!;
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
  const style = (RY_STYLE[data.alignment] ?? RY_STYLE.neutral)!;
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
  const style = (ROOM_STYLE[room] ?? ROOM_STYLE.unknown)!;
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
  const style = (SHOCK_STYLE[data.primary] ?? SHOCK_STYLE.none)!;
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
                <div className="text-[10px] font-medium text-on-surface-variant/60">
                  {c.short}
                </div>
                <div
                  className={cn(
                    "text-[12px] font-num font-bold mt-0.5",
                    ch?.available ? "text-on-surface" : "text-on-surface-variant/30",
                  )}
                >
                  {ch?.available ? fmt(ch.move_5d) : "—"}
                </div>
                {ch?.available && (
                  <div className="text-[10px] text-on-surface-variant/60 font-num">
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
  const divStyle = (RFD_DIVERGENCE_STYLE[data.divergence] ?? RFD_DIVERGENCE_STYLE.mild)!;
  const impliedStyle = (RFD_DIRECTION_STYLE[data.implied] ?? RFD_DIRECTION_STYLE.neutral)!;
  const pricedStyle = (RFD_DIRECTION_STYLE[data.priced] ?? RFD_DIRECTION_STYLE.neutral)!;

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
// Narrative Divergence block
// ---------------------------------------------------------------------------

const ND_LABEL_STYLE: Record<string, { icon: string; color: string; bg: string; text: string }> = {
  confident_miss:      { icon: "▼", color: "text-error-dim",          bg: "bg-error-dim/10",    text: "Confident Miss"      },
  surprise_validation: { icon: "▲", color: "text-primary",            bg: "bg-primary/8",       text: "Surprise Validation" },
  aligned:             { icon: "◆", color: "text-on-surface-variant", bg: "bg-surface-container-highest", text: "Aligned"  },
  mixed:               { icon: "◇", color: "text-on-surface-variant", bg: "bg-surface-container-highest", text: "Mixed"    },
  validated:           { icon: "◆", color: "text-primary",            bg: "bg-primary/8",       text: "Validated"           },
  contradicted:        { icon: "▼", color: "text-error-dim",          bg: "bg-error-dim/10",    text: "Contradicted"        },
};

const ROLE_SIGNAL_COLOR: Record<RoleSignal, string> = {
  aligned:  "text-primary",
  contra:   "text-error-dim",
  mixed:    "text-on-surface-variant",
  no_data:  "text-on-surface-variant/40",
};

const ROLE_SIGNAL_LABEL: Record<RoleSignal, string> = {
  aligned:  "Aligned",
  contra:   "Contra",
  mixed:    "Mixed",
  no_data:  "—",
};

function NarrativeDivergenceBlock({ data }: { data: NarrativeDivergence }) {
  if (!data || !data.available || !data.label) return null;

  const style = ND_LABEL_STYLE[data.label] ?? { icon: "◆", color: "text-on-surface-variant", bg: "bg-surface-container-highest", text: "Aligned" };
  const hasCalibration = data.expected_rate != null && data.gap != null;

  return (
    <section className={cn(SECTION_CARD, "p-5")}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">
          Narrative Divergence
        </h4>
        <div className={cn("flex items-center gap-1.5 rounded-full px-2 py-0.5", style.bg)}>
          <span className={cn("text-xs font-bold leading-none", style.color)}>{style.icon}</span>
          <span className={cn("text-[9px] font-bold uppercase tracking-widest", style.color)}>
            {style.text}
          </span>
        </div>
      </div>

      {/* Rate comparison */}
      {hasCalibration && (
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div className="bg-surface-container-highest rounded px-3 py-2.5">
            <div className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mb-1">
              Actual validation
            </div>
            <div className={cn("text-[18px] font-bold font-num leading-none", style.color)}>
              {Math.round((data.actual_rate ?? 0) * 100)}%
            </div>
            <div className="text-[9px] text-on-surface-variant/50 mt-0.5 font-num">
              {data.n_supporting ?? 0}/{data.n_total ?? 0} tickers
            </div>
          </div>
          <div className="bg-surface-container-highest rounded px-3 py-2.5">
            <div className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mb-1">
              Calibrated base rate
            </div>
            <div className="text-[18px] font-bold font-num leading-none text-on-surface-variant">
              {Math.round((data.expected_rate ?? 0) * 100)}%
            </div>
            {data.n_calibration_events != null && (
              <div className="text-[9px] text-on-surface-variant/50 mt-0.5 font-num">
                n={data.n_calibration_events} events
              </div>
            )}
          </div>
        </div>
      )}

      {/* No-calibration single stat */}
      {!hasCalibration && data.actual_rate != null && (
        <div className="bg-surface-container-highest rounded px-3 py-2.5 mb-3 flex items-center gap-3">
          <div>
            <div className="text-[9px] uppercase tracking-widest text-on-surface-variant/50 mb-1">
              Validation rate
            </div>
            <div className={cn("text-[18px] font-bold font-num leading-none", style.color)}>
              {Math.round(data.actual_rate * 100)}%
            </div>
          </div>
          <div className="text-[10px] text-on-surface-variant/50 italic leading-snug">
            No calibration data yet
          </div>
        </div>
      )}

      {/* Role signals */}
      {(data.beneficiary_signal || data.loser_signal) && (
        <div className="flex items-center gap-4 mb-3">
          {data.beneficiary_signal && data.beneficiary_signal !== "no_data" && (
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/50">
                Beneficiaries
              </span>
              <span className={cn("text-[10px] font-bold", ROLE_SIGNAL_COLOR[data.beneficiary_signal])}>
                {ROLE_SIGNAL_LABEL[data.beneficiary_signal]}
              </span>
            </div>
          )}
          {data.loser_signal && data.loser_signal !== "no_data" && (
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/50">
                Losers
              </span>
              <span className={cn("text-[10px] font-bold", ROLE_SIGNAL_COLOR[data.loser_signal])}>
                {ROLE_SIGNAL_LABEL[data.loser_signal]}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Rationale */}
      {data.rationale && (
        <p className="text-[12px] text-on-surface leading-relaxed">
          {data.rationale}
        </p>
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
  const style = (SURPRISE_REGIME_STYLE[data.regime] ?? SURPRISE_REGIME_STYLE.mixed)!;
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
  const style = (TOT_CHANNEL_STYLE[data.dominant_channel] ?? TOT_CHANNEL_STYLE.mixed)!;
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

  const channelStyle = (RS_CHANNEL_STYLE[data.dominant_channel] ?? RS_CHANNEL_STYLE.mixed)!;
  const pressureKey = data.pressure_label ?? "contained";
  const pressureStyle = (RS_PRESSURE_STYLE[pressureKey] ?? RS_PRESSURE_STYLE.contained)!;
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
  const decay = (DECAY_STYLE[analog.decay] ?? DECAY_STYLE.Unknown)!;
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

      {/* Classification badges + match-dimension pills */}
      <div className="flex flex-wrap items-center gap-1.5 mb-3">
        <span className="text-[10px] px-2 py-0.5 rounded bg-surface-container text-on-surface-variant/75 font-medium">
          {analog.stage}
        </span>
        <span className="text-[10px] px-2 py-0.5 rounded bg-surface-container text-on-surface-variant/75 font-medium">
          {analog.persistence}
        </span>
        {analog.match_dimensions && analog.match_dimensions.length > 0 && (
          <>
            <span className="w-px h-2 bg-outline-variant/25 mx-0.5" />
            {analog.match_dimensions.map((d) => (
              <MatchDimensionPill key={d.dimension} dim={d} />
            ))}
          </>
        )}
      </div>

      {/* Topic-vs-regime mismatch banner — fires when the past case rhymes
          on topic but diverges on macro setup.  Keeps it compact: one line,
          muted coral tint, no icon (the pill strip above already signals
          the dimensions that diverged). */}
      {analog.topic_vs_regime_mismatch && analog.mismatch_note && (
        <div className="mb-3 px-2 py-1.5 rounded bg-[#c07070]/10 border-l-2 border-[#c07070]/50">
          <p className="text-[10px] text-[#c07070] leading-snug">
            {analog.mismatch_note}
          </p>
        </div>
      )}

      {/* Follow-through metrics — 3-column comparison grid */}
      <div className="grid grid-cols-3 gap-x-3 py-3 border-t border-b border-outline-variant/10 mb-3">
        <div>
          <span className="text-[10px] text-on-surface-variant/55 font-medium block mb-1">5d return</span>
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
          <span className="text-[10px] text-on-surface-variant/55 font-medium block mb-1">20d return</span>
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
          <span className="text-[10px] text-on-surface-variant/55 font-medium block mb-1">Pattern</span>
          <span className={cn(
            "inline-block text-[10px] font-medium px-2 py-0.5 rounded leading-none",
            decay.bg, decay.color,
          )}>
            {decay.label}
          </span>
        </div>
      </div>

      {/* Explainer — finance-useful "why this analog rhymes (or doesn't)".
          Prefers the structured explainer from analog_explainer.py; falls
          back to the legacy match_reason string for rows that pre-date the
          explainer enrichment. */}
      {(analog.explainer || analog.match_reason) && (
        <p className="text-[10px] text-on-surface-variant/55 leading-relaxed mt-auto">
          {analog.explainer ?? analog.match_reason}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Thesis Scorecard — compact 4-cell composite of the shipped engine reads:
//   cross-asset confirmation · timing profile · funding stress · policy room
// Placed high on the page so the user gets the at-a-glance "how does this
// setup look" before drilling into the detail blocks.
// ---------------------------------------------------------------------------

type ScoreTone = "primary" | "error" | "neutral";

const _TONE_DOT: Record<ScoreTone, string> = {
  primary: "bg-[#6ec6a5]",
  error:   "bg-[#c07070]",
  neutral: "bg-[#a89f91]",
};
const _TONE_TEXT: Record<ScoreTone, string> = {
  primary: "text-[#6ec6a5]",
  error:   "text-[#c07070]",
  neutral: "text-on-surface",
};

function _crossAssetScoreCell(cx?: CrossAssetConfirmation | null): {
  value: string; sub: string; tone: ScoreTone;
} {
  if (!cx || !cx.available) {
    return { value: "—", sub: "not scored", tone: "neutral" };
  }
  const v = cx.verdict ?? "silent";
  const tone: ScoreTone =
    v === "strong_confirm" || v === "weak_confirm" ? "primary" :
    v === "strong_disconfirm" || v === "weak_disconfirm" ? "error" :
    "neutral";
  const value =
    v === "strong_confirm"    ? "Strong confirm" :
    v === "weak_confirm"      ? "Confirm" :
    v === "mixed"             ? "Mixed" :
    v === "weak_disconfirm"   ? "Disconfirm" :
    v === "strong_disconfirm" ? "Strong disconfirm" :
    "Silent";
  const sub = `${(cx.confirm_score ?? 0).toFixed(1)} confirm · ${(cx.disconfirm_score ?? 0).toFixed(1)} disconfirm`;
  return { value, sub, tone };
}

function _timingProfileCell(hc?: HorizonCheckpoints | null): {
  value: string; sub: string; tone: ScoreTone;
} {
  if (!hc || !hc.timing_profile || hc.timing_profile === "unknown") {
    return { value: "Unknown", sub: "no timing read", tone: "neutral" };
  }
  const p = hc.timing_profile;
  const value =
    p === "fast_shock"           ? "Fast shock" :
    p === "delayed_pass_through" ? "Delayed passthrough" :
    p === "slow_grind"           ? "Slow grind" :
    "Unknown";
  const sub =
    p === "fast_shock"           ? "reaction priced in <1d" :
    p === "delayed_pass_through" ? "5d–20d follow-through" :
    p === "slow_grind"           ? "20d+ structural" :
    "";
  return { value, sub, tone: "neutral" };
}

function _fundingStressCell(ct?: CreditTransmission | null): {
  value: string; sub: string; tone: ScoreTone;
} {
  if (!ct || !ct.available) {
    return { value: "—", sub: "credit inputs unavailable", tone: "neutral" };
  }
  const f = ct.funding_stress;
  const tone: ScoreTone =
    f === "acute" || f === "elevated" ? "error" :
    f === "insulated"                 ? "primary" :
    "neutral";
  const value =
    f === "acute"      ? "Acute" :
    f === "elevated"   ? "Elevated" :
    f === "contained"  ? "Contained" :
    f === "insulated"  ? "Insulated" :
    "Unknown";
  const evc = ct.equity_vs_credit;
  const sub =
    evc === "synchronized_stress"       ? "equity + credit stress" :
    evc === "credit_only_deterioration" ? "credit-only deterioration" :
    evc === "equity_only_riskoff"       ? "equity-only risk-off" :
    evc === "synchronized_calm"         ? "equity + credit calm" :
    "";
  return { value, sub, tone };
}

function _policyRoomCell(pc?: PolicyConstraint | null): {
  value: string; sub: string; tone: ScoreTone;
} {
  if (!pc || !pc.policy_room || pc.policy_room === "unknown") {
    return { value: "Unknown", sub: "no macro read", tone: "neutral" };
  }
  const r = pc.policy_room;
  const tone: ScoreTone =
    r === "boxed_in" || r === "constrained" ? "error" :
    r === "free_to_respond" || r === "ample" ? "primary" :
    "neutral";
  const value =
    r === "free_to_respond" ? "Free to respond" :
    r === "ample"           ? "Ample room" :
    r === "limited"         ? "Limited room" :
    r === "constrained"     ? "Constrained" :
    r === "boxed_in"        ? "Boxed in" :
    r === "mixed"           ? "Mixed mandate" :
    "Unknown";
  const sub = pc.binding_label
    ? `binding: ${pc.binding_label.toLowerCase()}`
    : "";
  return { value, sub, tone };
}

function ThesisScorecard({ analysis }: { analysis: AnalysisDetail }) {
  const cross = analysis.cross_asset_confirmation;
  const hc    = analysis.horizon_checkpoints;
  const ct    = analysis.credit_transmission;
  const pc    = analysis.policy_constraint;

  // Skip the whole card if every engine output is empty — avoids an
  // empty-row on low-signal responses.
  const anyAvailable =
    (cross && cross.available) ||
    (hc && hc.timing_profile && hc.timing_profile !== "unknown") ||
    (ct && ct.available) ||
    (pc && pc.policy_room && pc.policy_room !== "unknown");
  if (!anyAvailable) return null;

  const cells = [
    { kicker: "Cross-asset",  ..._crossAssetScoreCell(cross) },
    { kicker: "Timing",       ..._timingProfileCell(hc) },
    { kicker: "Funding",      ..._fundingStressCell(ct) },
    { kicker: "Policy room",  ..._policyRoomCell(pc) },
  ];

  return (
    <section className={cn(SECTION_CARD, "px-5 py-4")}>
      <div className="flex items-center justify-between mb-3">
        <p className="section-kicker">Thesis Scorecard</p>
        <span className="text-[9px] text-on-surface-variant/35 uppercase tracking-[0.2em]">
          at analysis time
        </span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
        {cells.map((c) => (
          <div key={c.kicker} className={cn(INNER_CARD, "p-3")}>
            <div className="flex items-center gap-1.5 mb-2">
              <span className={cn("w-1.5 h-1.5 rounded-full", _TONE_DOT[c.tone])} />
              <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-on-surface-variant/50">
                {c.kicker}
              </span>
            </div>
            <div className={cn("text-[13px] font-headline font-semibold leading-tight", _TONE_TEXT[c.tone])}>
              {c.value}
            </div>
            {c.sub && (
              <p className="text-[10px] text-on-surface-variant/45 mt-1 leading-snug">
                {c.sub}
              </p>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Sector Rotation Impact Map — renders sector_passthrough.
// Direct-hit sectors as lead pills; each downstream candidate as a compact
// row with lag pill, intensity dots, sign arrow, example tickers.  The
// distinction between direct (1-5d) and downstream (5-20d) validation
// windows shows up in the block header.
// ---------------------------------------------------------------------------

const _LAG_LABEL: Record<string, string> = {
  immediate: "Now", days: "Days", weeks: "Weeks", quarters: "Quarters",
};

const _INTENSITY_DOTS: Record<string, number> = { low: 1, medium: 2, high: 3 };

function _signGlyph(sign: SectorPassthroughEntry["sign"]): { g: string; cls: string } {
  if (sign === "reinforcing") return { g: "↑", cls: "text-[#6ec6a5]" };
  if (sign === "inverse")     return { g: "↓", cls: "text-[#c07070]" };
  return { g: "⇅", cls: "text-on-surface-variant/60" };
}

function _timingProfileLabel(p?: SectorPassthrough["timing_profile"]): string {
  if (p === "fast_cascade")  return "Fast cascade";
  if (p === "slow_cascade")  return "Slow cascade";
  if (p === "mixed")         return "Mixed cascade";
  if (p === "no_downstream") return "No cascade mapped";
  return "—";
}

// ---------------------------------------------------------------------------
// Finance Playbook — mechanism family + first/second-order channel packs +
// regime-conditioned caveat.  The "what does a macro desk do with this"
// header strip that sits right under the Thesis Scorecard.
// ---------------------------------------------------------------------------

const _FAMILY_LABEL: Record<MechanismFamily, string> = {
  tariff:                  "Tariff",
  sanction:                "Sanction",
  supply_shock:            "Supply shock",
  ceasefire_deescalation:  "Ceasefire / de-escalation",
  policy_surprise:         "Policy surprise",
  fiscal_issuance:         "Fiscal / issuance",
  labor_inflation:         "Labor / inflation print",
  bank_stress:             "Bank / funding stress",
  commodity_squeeze:       "Commodity squeeze",
  supply_normalization:    "Supply normalization",
  none:                    "No family matched",
};

const _CHANNEL_LABEL: Record<ExpectedChannel, string> = {
  rates:       "Rates",
  fx:          "FX",
  commodities: "Commodities",
  vol:         "Vol",
  credit:      "Credit",
  equities:    "Equities",
};

const _CHANNEL_GLYPH: Record<ExpectedChannel, string> = {
  rates:       "◧",
  fx:          "$",
  commodities: "●",
  vol:         "△",
  credit:      "⊖",
  equities:    "▣",
};

function ChannelChip({
  channel, tier,
}: { channel: ExpectedChannel; tier: "first" | "second" }) {
  const tierClass = tier === "first"
    ? "bg-primary-container/30 text-primary"
    : "bg-surface-container text-on-surface-variant/80";
  return (
    <span className={cn(
      "inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider leading-none",
      tierClass,
    )}>
      <span className="font-mono text-[9px] opacity-75">{_CHANNEL_GLYPH[channel]}</span>
      {_CHANNEL_LABEL[channel]}
    </span>
  );
}

function FinancePlaybookBlock({ analysis }: { analysis: AnalysisDetail }) {
  const fam = analysis.mechanism_family;
  const first = analysis.expected_first_order_channels ?? [];
  const second = analysis.expected_second_order_channels ?? [];
  const caveat = (analysis.regime_conditioned_caveat ?? "").trim();

  // Card hides entirely when the family is missing/none AND both channel
  // packs are empty — no value in an empty playbook strip on thin events.
  const hasFamily = fam && fam !== "none";
  const hasChannels = first.length > 0 || second.length > 0;
  if (!hasFamily && !hasChannels) return null;

  const familyLabel = fam ? (_FAMILY_LABEL[fam] ?? fam) : "Unclassified";
  const noCaveat = !caveat || /no regime-conditioned caveat/i.test(caveat);

  return (
    <section className={cn(SECTION_CARD, "px-5 py-4")}>
      <div className="flex items-center justify-between mb-3">
        <p className="section-kicker">Finance Playbook</p>
        <span className="text-[9px] text-on-surface-variant/35 uppercase tracking-[0.2em]">
          canonical desk read
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-x-5 gap-y-3 items-start">
        {/* Left: mechanism family + archetype line */}
        <div className={cn(INNER_CARD, "px-4 py-3 min-w-[180px]")}>
          <span className="nav-kicker block mb-1.5">Archetype</span>
          <div className={cn(
            "text-[14px] font-headline font-semibold leading-tight",
            hasFamily ? "text-on-surface" : "text-on-surface-variant/50",
          )}>
            {familyLabel}
          </div>
        </div>

        {/* Right: channel packs */}
        <div className="flex flex-col gap-2.5 justify-center min-w-0">
          {first.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-on-surface-variant/50 mr-1 shrink-0">
                First order
              </span>
              {first.map((c) => <ChannelChip key={c} channel={c} tier="first" />)}
            </div>
          )}
          {second.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-on-surface-variant/50 mr-1 shrink-0">
                Cascade
              </span>
              {second.map((c) => <ChannelChip key={c} channel={c} tier="second" />)}
            </div>
          )}
        </div>
      </div>

      {/* Regime-conditioned caveat — the "how today's backdrop bends this
          playbook" line.  Only rendered when the LLM committed to a real
          caveat (the placeholder sentence is suppressed). */}
      {!noCaveat && (
        <div className="mt-3 pt-3 border-t border-outline-variant/10">
          <div className="flex items-start gap-2">
            <span className="w-1 h-3 bg-primary/50 rounded-full shrink-0 mt-[3px]" />
            <div className="min-w-0">
              <span className="nav-kicker block mb-1">Regime-conditioned caveat</span>
              <p className="text-[11px] text-on-surface/80 leading-relaxed italic">
                {caveat}
              </p>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Base Case / Key Risk / What Would Change The Read — the three-column
// "macro note" summary that compresses mechanism + counterforces +
// adversarial_challenge into a decision-useful header.
// ---------------------------------------------------------------------------

const _LIKELIHOOD_DOT: Record<string, string> = {
  high:   "bg-[#c07070]",
  medium: "bg-[#a89f91]",
  low:    "bg-outline-variant/30",
};
const _SEVERITY_DOT: Record<string, string> = {
  high:   "bg-[#c07070]",
  medium: "bg-[#a89f91]",
  low:    "bg-outline-variant/30",
};

function _leadSentence(text: string): string {
  if (!text) return "";
  const match = text.match(/[^.!?]+[.!?]/);
  return (match ? match[0] : text).trim();
}

function BaseCaseRiskBlock({ analysis }: { analysis: AnalysisDetail }) {
  const base = _leadSentence(analysis.mechanism_summary || analysis.what_changed || "");
  const counterforces = (analysis.counterforces ?? []).slice(0, 3);
  const barriers = (analysis.substitution_barriers ?? []).slice(0, 2);
  const adversarial = (analysis.adversarial_challenge ?? "").trim();
  const hasAdversarial = adversarial && !/^no credible challenge/i.test(adversarial);

  // Hide the block if every column is empty — the Analysis page already
  // carries what_changed / mechanism_summary in a separate section above.
  if (!base && counterforces.length === 0 && barriers.length === 0 && !hasAdversarial) {
    return null;
  }

  return (
    <section className={cn(SECTION_CARD, "p-6")}>
      <div className="flex items-center justify-between mb-4">
        <p className="section-kicker">Macro Note</p>
        <span className="text-[9px] text-on-surface-variant/35 uppercase tracking-[0.2em]">
          base · risk · falsifier
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {/* Base case */}
        <div className={cn(INNER_CARD, "p-4 border-l-2 border-[#6ec6a5]/60")}>
          <span className="nav-kicker text-[#6ec6a5]/90 block mb-2">Base case</span>
          <p className="text-[11.5px] text-on-surface leading-relaxed">
            {base || <span className="text-on-surface-variant/40 italic">No first-order read.</span>}
          </p>
        </div>

        {/* Key risk — counterforces (primary) + substitution barriers (secondary) */}
        <div className={cn(INNER_CARD, "p-4 border-l-2 border-[#c07070]/60")}>
          <span className="nav-kicker text-[#c07070]/90 block mb-2">Key risk</span>
          {counterforces.length > 0 ? (
            <ul className="space-y-2">
              {counterforces.map((c: Counterforce, i: number) => (
                <li key={i} className="flex items-start gap-2">
                  <span
                    className={cn(
                      "w-1.5 h-1.5 rounded-full shrink-0 mt-[5px]",
                      _LIKELIHOOD_DOT[c.likelihood] ?? _LIKELIHOOD_DOT.medium,
                    )}
                    title={`likelihood: ${c.likelihood}`}
                  />
                  <div className="min-w-0">
                    <p className="text-[11px] text-on-surface leading-snug">
                      {c.force}
                    </p>
                    {c.actor && (
                      <span className="text-[9px] text-on-surface-variant/45 block mt-0.5 uppercase tracking-widest">
                        {c.actor}
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[11px] text-on-surface-variant/40 italic">
              No structured counterforces.
            </p>
          )}
          {barriers.length > 0 && (
            <div className="mt-3 pt-3 border-t border-outline-variant/10">
              <span className="nav-kicker block mb-1.5">Substitution barriers</span>
              <ul className="space-y-1">
                {barriers.map((b: SubstitutionBarrier, i: number) => (
                  <li key={i} className="flex items-start gap-2">
                    <span
                      className={cn(
                        "w-1 h-1 rounded-full shrink-0 mt-[6px]",
                        _SEVERITY_DOT[b.severity] ?? _SEVERITY_DOT.medium,
                      )}
                      title={`severity: ${b.severity}`}
                    />
                    <p className="text-[10.5px] text-on-surface-variant/80 leading-snug">
                      {b.barrier}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* What would change the read — adversarial_challenge */}
        <div className={cn(INNER_CARD, "p-4 border-l-2 border-[#a89f91]/60")}>
          <span className="nav-kicker text-[#a89f91]/90 block mb-2">
            What would change the read
          </span>
          {hasAdversarial ? (
            <p className="text-[11.5px] text-on-surface leading-relaxed">
              {adversarial}
            </p>
          ) : (
            <p className="text-[11px] text-on-surface-variant/40 italic">
              No credible counter-thesis identified — mechanism is direct.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Horizon Checkpoints — 1d / 5d / 20d × expected / confirms_if / falsifies_if.
// The headline decision-useful block: what should happen next, and what
// would prove the thesis wrong at each horizon.
// ---------------------------------------------------------------------------

const _TIMING_PROFILE_LABEL: Record<string, { label: string; sub: string; tone: ScoreTone }> = {
  fast_shock:           { label: "Fast shock",           sub: "reaction priced in <1d",   tone: "neutral" },
  delayed_pass_through: { label: "Delayed passthrough",  sub: "5d–20d follow-through",    tone: "neutral" },
  slow_grind:           { label: "Slow grind",           sub: "20d+ structural",          tone: "neutral" },
  unknown:              { label: "Unknown",              sub: "no timing committed",      tone: "neutral" },
};

function _bulletColumn(
  kicker: string,
  tone: "confirm" | "expected" | "falsify",
  items: string[],
): JSX.Element {
  const toneClass =
    tone === "confirm"  ? "text-[#6ec6a5]" :
    tone === "falsify"  ? "text-[#c07070]" :
    "text-on-surface-variant/70";
  const dotClass =
    tone === "confirm"  ? "bg-[#6ec6a5]" :
    tone === "falsify"  ? "bg-[#c07070]" :
    "bg-outline-variant/35";
  return (
    <div>
      <span className={cn("nav-kicker block mb-1.5", toneClass)}>{kicker}</span>
      {items.length === 0 ? (
        <p className="text-[10.5px] text-on-surface-variant/35 italic">— no entry —</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((t, i) => (
            <li key={i} className="flex items-start gap-1.5">
              <span className={cn("w-1 h-1 rounded-full shrink-0 mt-[6px]", dotClass)} />
              <span className="text-[10.5px] text-on-surface/90 leading-snug">{t}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function HorizonRow({ h }: { h: HorizonCheckpoint }) {
  const isEmpty =
    h.expected.length === 0 &&
    h.confirms_if.length === 0 &&
    h.falsifies_if.length === 0;
  return (
    <div className={cn(
      INNER_CARD, "p-4 grid grid-cols-1 md:grid-cols-[48px_1fr_1fr_1fr] gap-4",
      isEmpty && "opacity-40",
    )}>
      {/* Horizon stamp */}
      <div className="flex md:flex-col md:items-start items-center gap-2 md:gap-0.5 md:border-r border-outline-variant/10 md:pr-4">
        <span className="text-[22px] font-headline font-extrabold text-on-surface leading-none tabular-nums">
          {h.horizon}
        </span>
        <span className="text-[9px] uppercase tracking-[0.2em] text-on-surface-variant/45 font-bold">
          horizon
        </span>
      </div>
      {_bulletColumn("Expected", "expected", h.expected)}
      {_bulletColumn("Confirms if", "confirm", h.confirms_if)}
      {_bulletColumn("Falsifies if", "falsify", h.falsifies_if)}
    </div>
  );
}

function HorizonCheckpointsBlock({ data }: { data: HorizonCheckpoints }) {
  if (!data || !data.horizons || data.horizons.length === 0) return null;
  // Suppress the block entirely when every horizon is empty on all three
  // axes AND the timing profile is unknown — nothing finance-real to show.
  const anyEntry = data.horizons.some(
    (h) => h.expected.length + h.confirms_if.length + h.falsifies_if.length > 0,
  );
  const timingUsable = data.timing_profile && data.timing_profile !== "unknown";
  if (!anyEntry && !timingUsable) return null;

  const profile =
    _TIMING_PROFILE_LABEL[data.timing_profile]
    ?? _TIMING_PROFILE_LABEL.unknown!;

  return (
    <section className={cn(SECTION_CARD, "p-6")}>
      <div className="flex items-start justify-between mb-4 gap-4">
        <div className="flex items-center gap-2">
          <span className="w-1 h-3 bg-primary rounded-full shrink-0" />
          <div>
            <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">
              Horizon Checkpoints
            </h4>
            <p className="text-[10px] text-on-surface-variant/40 mt-0.5">
              what should happen next · what would prove this wrong
            </p>
          </div>
        </div>
        {/* Timing profile pill */}
        <div className="flex items-center gap-2 shrink-0 mt-0.5">
          <div className={cn("px-2.5 py-1 rounded-full", INNER_CARD)}>
            <div className="flex items-center gap-1.5">
              <span className={cn("w-1.5 h-1.5 rounded-full", _TONE_DOT[profile.tone])} />
              <span className="text-[10px] font-bold text-on-surface uppercase tracking-widest leading-none">
                {profile.label}
              </span>
            </div>
            <span className="text-[9px] text-on-surface-variant/45 leading-none block mt-1">
              {profile.sub}
            </span>
          </div>
        </div>
      </div>

      <div className="space-y-2.5">
        {data.horizons.map((h) => (
          <HorizonRow key={h.horizon} h={h} />
        ))}
      </div>
    </section>
  );
}

function SectorPassthroughBlock({ data }: { data: SectorPassthrough }) {
  if (!data || !data.available) return null;
  const direct = data.direct_sectors_label ?? [];
  const down = data.downstream ?? [];

  return (
    <section className={cn(SECTION_CARD, "p-6")}>
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="w-1 h-3 bg-primary rounded-full shrink-0" />
          <div>
            <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">
              Sector Rotation Impact
            </h4>
            <p className="text-[10px] text-on-surface-variant/40 mt-0.5">
              {_timingProfileLabel(data.timing_profile)} · direct {data.direct_validation_window} ·
              {" "}downstream {data.downstream_validation_window}
            </p>
          </div>
        </div>
      </div>

      {/* Direct hit row */}
      {direct.length > 0 && (
        <div className="mb-4">
          <span className="nav-kicker block mb-2">Direct hit</span>
          <div className="flex flex-wrap gap-1.5">
            {direct.map((label) => (
              <span
                key={label}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary-container/30 text-[10px] font-bold text-primary tracking-wide"
              >
                <span className="w-1 h-1 rounded-full bg-primary" />
                {label}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Downstream grid */}
      {down.length > 0 ? (
        <div>
          <span className="nav-kicker block mb-2">Downstream</span>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {down.map((entry, i) => {
              const sg = _signGlyph(entry.sign);
              const dots = _INTENSITY_DOTS[entry.intensity] ?? 1;
              return (
                <div
                  key={`${entry.source}-${entry.target}-${i}`}
                  className={cn(INNER_CARD, "p-3")}
                >
                  <div className="flex items-center justify-between gap-2 mb-1.5">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className={cn("text-[14px] leading-none shrink-0", sg.cls)}>
                        {sg.g}
                      </span>
                      <span className="text-[11px] font-semibold text-on-surface truncate">
                        {entry.target_label}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="flex items-center gap-0.5">
                        {[0, 1, 2].map((n) => (
                          <span
                            key={n}
                            className={cn(
                              "w-1 h-1 rounded-full",
                              n < dots ? _TONE_DOT[entry.sign === "reinforcing" ? "primary" : entry.sign === "inverse" ? "error" : "neutral"] : "bg-outline-variant/20",
                            )}
                          />
                        ))}
                      </span>
                      <span className="text-[9px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant/60">
                        {_LAG_LABEL[entry.lag] ?? entry.lag}
                      </span>
                    </div>
                  </div>
                  <p className="text-[10px] text-on-surface-variant/55 leading-snug mb-1.5">
                    {entry.mechanism}
                  </p>
                  {entry.example_proxies && entry.example_proxies.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {entry.example_proxies.slice(0, 5).map((p) => (
                        <span
                          key={p}
                          className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-surface-container/60 text-on-surface-variant/75"
                        >
                          {p}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <p className="text-[10px] text-on-surface-variant/40 italic">
          No structured downstream cascade mapped for this direct-hit set.
        </p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Analog match-dimension pill — renders one entry from match_dimensions.
// ---------------------------------------------------------------------------

const _DIM_STATUS: Record<AnalogMatchDimension["status"], {
  dot: string; text: string; bg: string; glyph: string;
}> = {
  match:    { dot: "bg-[#6ec6a5]", text: "text-[#6ec6a5]", bg: "bg-[#6ec6a5]/10", glyph: "✓" },
  partial:  { dot: "bg-[#a89f91]", text: "text-[#a89f91]", bg: "bg-[#a89f91]/10", glyph: "≈" },
  mismatch: { dot: "bg-[#c07070]", text: "text-[#c07070]", bg: "bg-[#c07070]/10", glyph: "✗" },
  unknown:  { dot: "bg-outline-variant/30", text: "text-on-surface-variant/40", bg: "bg-surface-container/40", glyph: "·" },
};

const _DIM_SHORT_LABEL: Record<string, string> = {
  mechanism_family: "Family",
  regime:           "Regime",
  inflation_rates:  "Rates",
  credit:           "Credit",
};

function MatchDimensionPill({ dim }: { dim: AnalogMatchDimension }) {
  const style = _DIM_STATUS[dim.status];
  const short = _DIM_SHORT_LABEL[dim.dimension] ?? dim.label;
  return (
    <span
      title={dim.note}
      className={cn(
        "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-widest leading-none",
        style.bg, style.text,
      )}
    >
      <span className={cn("leading-none", style.text)}>{style.glyph}</span>
      {short}
    </span>
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
  // "Aligned" (not "Confirmed") — the tape is moving with the thesis at the
  // ticker level; muted jade for supportive, rust for inverted, slate for
  // pending.  Citrine stays chrome-only.
  if (isSupporting(t)) return { label: "Aligned", cls: "bg-[rgba(152,194,173,0.12)] text-[var(--so-jade-ink)]" };
  if (isContradicting(t)) return { label: "Inverted", cls: "bg-[rgba(224,151,140,0.12)] text-[var(--so-rust-ink)]" };
  return { label: "Pending", cls: "bg-[rgba(122,134,148,0.10)] text-[var(--so-slate)]" };
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
        <div className={cn("mt-2 text-[10px] font-bold", r5 > 0 ? "text-[var(--so-jade-ink)]" : r5 < 0 ? "text-[var(--so-rust-ink)]" : "text-[var(--so-slate)]")}>
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

// ---------------------------------------------------------------------------
// Revisit Timeline — multi-timeframe follow-through section
// ---------------------------------------------------------------------------

const _VERDICT_STYLE: Record<string, { label: string; color: string; bg: string }> = {
  validated:    { label: "Validated",    color: "text-[var(--so-jade-ink)]", bg: "bg-[rgba(152,194,173,0.10)]" },
  contradicted: { label: "Contradicted", color: "text-[var(--so-rust-ink)]", bg: "bg-[rgba(224,151,140,0.10)]" },
  mixed:        { label: "Mixed",        color: "text-[var(--so-slate)]",    bg: "bg-surface-container-highest" },
  no_data:      { label: "Pending",      color: "text-[var(--so-ink-3)]",    bg: "bg-surface-container-highest/30" },
};

const _TRAJECTORY_STYLE: Record<ThesisTrajectory, { label: string; icon: typeof TrendingUp; color: string }> = {
  holding:   { label: "Thesis holding",  icon: TrendingUp,   color: "text-[var(--so-jade-ink)]" },
  fading:    { label: "Signal fading",   icon: TrendingDown,  color: "text-[var(--so-slate)]" },
  reversed:  { label: "Thesis reversed", icon: TrendingDown,  color: "text-[var(--so-rust-ink)]" },
  mixed:     { label: "Mixed signals",   icon: AlertTriangle, color: "text-[var(--so-slate)]" },
  too_early: { label: "Too early",       icon: Clock,         color: "text-[var(--so-ink-3)]" },
};

function HorizonColumn({ h }: { h: HorizonSummary }) {
  const vs = (_VERDICT_STYLE[h.verdict] ?? _VERDICT_STYLE.no_data)!;
  return (
    <div className={cn(
      "flex-1 min-w-[120px] rounded-lg p-3",
      h.available ? "bg-surface-container-highest" : "bg-surface-container-highest/15 opacity-50",
    )}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-on-surface-variant/60">{h.label}</span>
        <span className={cn("text-[9px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded", vs.bg, vs.color)}>
          {vs.label}
        </span>
      </div>

      {/* Avg return */}
      {h.avgReturn != null ? (
        <div className={cn(
          "text-[18px] font-bold tabular-nums leading-none mb-2",
          h.avgReturn > 0.2 ? "text-[var(--so-jade-ink)]" : h.avgReturn < -0.2 ? "text-[var(--so-rust-ink)]" : "text-[var(--so-slate)]",
        )}>
          {h.avgReturn > 0 ? "+" : ""}{h.avgReturn.toFixed(1)}%
        </div>
      ) : (
        <div className="text-[18px] font-bold text-on-surface-variant/20 leading-none mb-2">&mdash;</div>
      )}

      {/* Support ratio */}
      {h.total > 0 && (
        <div className="text-[9px] text-on-surface-variant/50 mb-2">
          {h.supporting}/{h.total} supporting
        </div>
      )}

      {/* Per-ticker rows */}
      {h.tickers.length > 0 && (
        <div className="space-y-1">
          {h.tickers.map((t) => (
            <div key={t.symbol} className="flex items-center justify-between text-[10px]">
              <div className="flex items-center gap-1 min-w-0">
                {t.direction === "supports" && <TrendingUp className="w-2.5 h-2.5 text-primary shrink-0" />}
                {t.direction === "contradicts" && <TrendingDown className="w-2.5 h-2.5 text-error-dim shrink-0" />}
                {t.direction === "neutral" && <span className="w-2.5 h-2.5 shrink-0" />}
                <span className="font-medium text-on-surface/80 truncate">{t.symbol}</span>
              </div>
              {t.returnValue != null ? (
                <span className={cn(
                  "font-num font-bold tabular-nums",
                  t.returnValue > 0 ? "text-primary" : t.returnValue < 0 ? "text-error-dim" : "text-on-surface-variant",
                )}>
                  {t.returnValue > 0 ? "+" : ""}{t.returnValue.toFixed(1)}%
                </span>
              ) : (
                <span className="text-on-surface-variant/30">&mdash;</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RevisitTimeline({
  eventId,
  snapshots: initial,
}: {
  eventId: number;
  snapshots: RevisitSnapshot[];
}) {
  const [snapshots, setSnapshots] = useState<RevisitSnapshot[]>(initial);
  const [capturing, setCapturing] = useState(false);

  useEffect(() => {
    if (initial.length > 0) return;
    let cancelled = false;
    api.getRevisitTimeline(eventId).then((res) => {
      if (!cancelled) setSnapshots(res.snapshots);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [eventId, initial.length]);

  const capture = useCallback(async () => {
    setCapturing(true);
    try {
      const res = await api.captureRevisit(eventId);
      setSnapshots(res.snapshots);
    } catch { /* silent */ }
    finally { setCapturing(false); }
  }, [eventId]);

  const horizons = deriveAllHorizons(snapshots);
  const trajectory = deriveTrajectory(horizons);
  const traj = _TRAJECTORY_STYLE[trajectory];
  const TrajIcon = traj.icon;
  const hasAny = horizons.some((h) => h.available);

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-start justify-between">
        <div>
          <p className="section-kicker mb-1.5">Revisit Timeline</p>
          {hasAny ? (
            <span
              className={cn("flex items-center gap-1.5 text-[13px] font-semibold leading-none", traj.color)}
              style={{ fontFamily: "'Manrope', 'Inter', sans-serif" }}
            >
              <TrajIcon className="w-3.5 h-3.5" />
              {traj.label}
            </span>
          ) : (
            <span className="text-[11px] text-on-surface-variant/35 italic">No follow-through data yet</span>
          )}
        </div>
        <button
          onClick={capture}
          disabled={capturing}
          className="flex items-center gap-1.5 text-[10px] text-primary/60 hover:text-primary transition-colors disabled:opacity-40 mt-0.5"
        >
          <RefreshCw className={cn("w-3 h-3", capturing && "animate-spin")} />
          {capturing ? "Capturing…" : "Capture now"}
        </button>
      </div>

      {/* Four-column horizon grid (1d / 5d / 20d / 60d) */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {horizons.map((h) => (
          <HorizonColumn key={h.day} h={h} />
        ))}
      </div>
    </div>
  );
}

function _buildWhyNote(ticker: Ticker, analysis: AnalysisDetail): string {
  const role = ticker.role;
  const sd = analysis.shock_decomposition;
  const ps = analysis.policy_sensitivity;

  // Tier 1: shock-anchored note
  if (sd?.primary_label && sd.primary !== "none") {
    const connector = role === "beneficiary" ? "beneficiary through" : "exposed via";
    const channelRaw = sd.rationale || analysis.mechanism_summary || "";
    const channel = channelRaw.length > 80 ? channelRaw.slice(0, 77) + "…" : channelRaw;
    return `${sd.primary_label} — ${connector} ${channel}`;
  }

  // Tier 2: policy-sensitive note
  if ((ps?.stance === "reinforced" || ps?.stance === "fighting") && ps?.explanation) {
    const prefix = ps.stance === "fighting" ? "Policy headwind" : "Policy-sensitive";
    const expl = ps.explanation.length > 100 ? ps.explanation.slice(0, 97) + "…" : ps.explanation;
    return `${prefix} — ${expl}`;
  }

  // Tier 3: mechanism fallback
  const mech = analysis.mechanism_summary || "";
  const mechTrunc = mech.length > 110 ? mech.slice(0, 107) + "…" : mech;
  if (!mechTrunc) return "";
  return role === "beneficiary"
    ? `Beneficiary — ${mechTrunc}`
    : `Exposed to downside — ${mechTrunc}`;
}

function MarketSection({ tickers, eventDate, analysis }: { tickers: Ticker[]; eventDate?: string; analysis?: AnalysisDetail }) {
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
        <div className="az-tickerdetail">
        <TickerDetailPanel
          ticker={selectedTicker}
          eventDate={eventDate}
          extra={{
            label: selectedTicker.label,
            direction_tag: selectedTicker.direction_tag,
            return_1d: selectedTicker.return_1d,
            volume_ratio: selectedTicker.volume_ratio,
            vs_xle_5d: selectedTicker.vs_xle_5d,
            why: analysis ? _buildWhyNote(selectedTicker, analysis) : undefined,
          }}
        />
        </div>
      )}
      {withDir.length > 0 && (
        <p className="font-mono text-[10px] text-[var(--so-ink-3)]">
          Hypothesis: <span className={cn("font-bold", supportCount === withDir.length && "text-[var(--so-jade-ink)]", supportCount === 0 && "text-[var(--so-rust-ink)]")}>{supportCount}/{withDir.length}</span> directional tickers aligned at 1d
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
  /** Called when analysis completes as failed (analysis_failed) or mock
   *  (is_mock).  HeadlinesPage uses this to mark the row as retryable. */
  onAnalysisFailed?: (headline: string) => void;
  /** Called when analysis completes successfully (not failed, not mock).
   *  HeadlinesPage uses this to clear a previously-failed row back to normal. */
  onAnalysisSucceeded?: (headline: string) => void;
}

type Phase = "idle" | "classify" | "analysis" | "market" | "complete";

export function AnalysisView({ initialHeadline, initialContext, initialEventId, onHeadlineConsumed, onBack, onAnalysisFailed, onAnalysisSucceeded }: AnalysisViewProps) {
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
  const onAnalysisFailedRef = useRef(onAnalysisFailed);
  onAnalysisFailedRef.current = onAnalysisFailed;
  const onAnalysisSucceededRef = useRef(onAnalysisSucceeded);
  onAnalysisSucceededRef.current = onAnalysisSucceeded;
  const loading = phase !== "idle" && phase !== "complete";

  const { data: calibData } = useQuery<ConfidenceCalibration>({
    queryKey: qk.confidenceCalibration(),
    queryFn: api.confidenceCalibration,
    staleTime: 300_000,
    retry: 1,
  });

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
            const resp = data as unknown as AnalyzeResponse;
            if (resp.analysis_failed || resp.is_mock) {
              onAnalysisFailedRef.current?.(text);
              setError(resp.failure_reason || "Model unavailable — try again in a moment.");
              setPhase("idle");
              return;
            }
            onAnalysisSucceededRef.current?.(text);
            setResult(resp);
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

  // --- Market-only refresh (no LLM re-run) ---
  const [marketRefreshing, setMarketRefreshing] = useState(false);

  const refreshMarket = useCallback(async () => {
    const eid = pendingEventIdRef.current;
    if (!eid || !result) return;
    setMarketRefreshing(true);
    try {
      const res = await api.refreshMarket(eid);
      setResult((prev) => prev ? { ...prev, market: res.market } : prev);
    } catch {
      // silent — market block stays as-is
    } finally {
      setMarketRefreshing(false);
    }
  }, [result]);

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

  const calibBucket = result?.analysis?.confidence && calibData
    ? calibData[result.analysis.confidence as Confidence]
    : undefined;

  const isLowSignal = result?.analysis
    && (result.analysis.mechanism_summary || "").toLowerCase().includes("insufficient evidence")
    && result.analysis.beneficiaries.length === 0
    && result.analysis.losers.length === 0;

  return (
    <div className="az-canvas pb-8">
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

      {/* ── EVENT IDENTITY — tag chips · display headline · metric row ── */}
      <div className="mb-9">
        {/* Tag row */}
        {(result?.stage || result?.persistence || result?.event_date || (result?.is_mock && !result?.analysis_failed)) && (
          <div className="mb-3.5 flex flex-wrap items-center gap-1.5">
            {result?.is_mock && !result?.analysis_failed && (
              <span className="az-mock-badge">mock fallback</span>
            )}
            {result?.stage && (
              <span className="az-tag"><span className="tk">stage</span>{result.stage}</span>
            )}
            {result?.persistence && (
              <span className="az-tag"><span className="tk">persistence</span>{result.persistence}</span>
            )}
            {result?.event_date && (
              <span className="az-tag"><span className="tk">event</span>{result.event_date}</span>
            )}
          </div>
        )}

        {/* Headline — display serif (input when idle) */}
        {result ? (
          <h1 className="az-headline max-w-[34ch]">{result.headline}</h1>
        ) : (
          <input
            type="text"
            placeholder="Paste a headline to analyze…"
            value={headline}
            onChange={(e) => setHeadline(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            className="az-headline w-full max-w-[34ch] bg-transparent placeholder:text-[var(--so-ink-4)] focus:outline-none"
          />
        )}

        {/* Metric row — confidence + live status, az-metric rhythm */}
        {((conf && result?.analysis) || loading) && (
          <div className="mt-4 flex flex-wrap items-baseline gap-x-9 gap-y-3">
            {conf && result?.analysis && (
              <div className="az-metric">
                <div className="ml">Confidence</div>
                <div className={cn("mv", `conf-${result.analysis.confidence}`)}>{conf.label}</div>
                {calibBucket && (
                  <div className="ms" title={`Historical validation rate for ${result.analysis.confidence}-confidence calls`}>
                    {Math.round(calibBucket.hit_rate * 100)}% validated historically, n={calibBucket.n}
                  </div>
                )}
              </div>
            )}
            {loading && (
              <div className="az-metric">
                <div className="ml">Status</div>
                <div className="mv inline-flex items-center gap-1.5" style={{ color: "var(--so-citrine)" }}>
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {phase === "analysis" ? "Mechanism…" : "Market…"}
                </div>
              </div>
            )}
          </div>
        )}
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

      {/* ── EVIDENCE QUALITY / SOURCE CONSENSUS ──
          Wrapped in the Analyze card language (charcoal surface, warm
          hairline, mono label).  The `az-consensus` hook lets the scoped
          stylesheet mute the evidence strip's loud teal/navy chips to
          jade/rust/charcoal without editing the shared component. */}
      {result && result.analysis && !isLowSignal && (
        <div className="az-consensus mb-6 rounded-[4px] border border-[color:var(--so-rule)] bg-[var(--so-bg-1)] px-4 py-3">
          <p className="az-card-title mb-2.5">Source Consensus</p>
          <EvidenceQualityStrip result={result} />
        </div>
      )}

      {/* ── RESULTS ── */}
      {result && (
        <div className="space-y-8">

          {/* ── STATE A: Strong signal — primary thesis stack ──
              Hierarchy: why surfaced → thesis → evidence / falsifiers →
              transmission → assets.  Macro context anchors WHY (regime
              forced this onto the radar); thesis and evidence/falsifiers
              are visually primary; transmission and assets follow.  Market
              validation, follow-through, then the collapsed backstage
              disclosures trail the read. */}
          {result.analysis && !isLowSignal && (
            <div className="space-y-8">
              {/* ============================================================
                  WHY SURFACED — macro context that frames why this matters now
                  ============================================================ */}
              <div className="space-y-4">
                <SectionLead num="01" title="Why surfaced" sub="Regime + release context that frames this read" />

                <section className={cn(SECTION_CARD, "px-5 py-3")}>
                  <MarketBackdropStrip />
                </section>

                <MacroBackdropBlock analysis={result.analysis} />

                {result.analysis.macro_release_context && (
                  <MacroReleaseContextBlock data={result.analysis.macro_release_context} />
                )}

                {result.analysis.policy_timing_context && (
                  <PolicyTimingContextBlock data={result.analysis.policy_timing_context} />
                )}

                {result.analysis.country_vulnerability_context && (
                  <CountryVulnerabilityContextBlock data={result.analysis.country_vulnerability_context} />
                )}
              </div>

              {/* ============================================================
                  THESIS — what changed + mechanism (lifted to primary)
                  ============================================================ */}
              <div className="space-y-4">
                <SectionLead num="02" title="What changed & how it transmits" sub="The thesis and its mechanism" />

                <div className={cn(SECTION_CARD, "p-6 space-y-5")}>
                  <div>
                    <SectionLabel>What Changed</SectionLabel>
                    <ul className="space-y-2.5">
                      {result.analysis.what_changed.split(/[.!]\s+/).filter(Boolean).map((s, i) => (
                        <li key={i} className="flex items-start gap-2.5">
                          <Check className="h-3.5 w-3.5 text-[var(--so-citrine)] shrink-0 mt-0.5" />
                          <p className="az-serif text-[13.5px] leading-relaxed">{s.trim().replace(/\.$/, "")}.</p>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="pt-5 border-t border-[color:var(--so-rule)]">
                    <h4 className="az-card-title mb-2">Mechanism Summary</h4>
                    <p className="az-serif text-[13px] leading-relaxed text-[var(--so-ink-2)] whitespace-pre-line">
                      {result.analysis.mechanism_summary}
                    </p>
                  </div>
                </div>

                {/* Mechanism family playbook + regime-conditioned caveat */}
                <FinancePlaybookBlock analysis={result.analysis} />

                {/* Base case + key risk + adversarial challenge */}
                <BaseCaseRiskBlock analysis={result.analysis} />
              </div>

              {/* ============================================================
                  EVIDENCE & FALSIFIERS — pre-committed tests, visually primary
                  ============================================================ */}
              <div className="space-y-4">
                <SectionLead num="03" title="Evidence & falsifiers" sub="Pre-committed tests — the thesis is only as good as these" />

                <ThesisScorecard analysis={result.analysis} />

                {result.analysis.horizon_checkpoints && (
                  <HorizonCheckpointsBlock data={result.analysis.horizon_checkpoints} />
                )}

                {result.analysis.if_persists && (
                  <section className={cn(SECTION_CARD, "p-6")}>
                    <h4 className="text-[11px] font-bold uppercase tracking-[0.2em] text-on-surface-variant mb-4">
                      If This Persists — Second-Order Effects
                    </h4>
                    <IfPersistsSection data={result.analysis.if_persists} />
                  </section>
                )}
              </div>

              {/* ============================================================
                  TRANSMISSION — how the thesis transmits, step-by-step
                  ============================================================ */}
              {result.analysis.transmission_chain && result.analysis.transmission_chain.length > 0 && (
                <div className="space-y-4">
                  <SectionLead num="04" title="Event to price, step by step" sub="The transmission path" />
                  <section className={cn(SECTION_CARD, "px-6 py-6")}>
                    <AzTransmissionChain steps={result.analysis.transmission_chain} />
                  </section>
                </div>
              )}

              {/* ============================================================
                  ASSETS — projected beneficiaries / losers
                  Market validation card sits immediately below this block.
                  ============================================================ */}
              <div className="space-y-4">
                <SectionLead num="05" title="Where it should & shouldn't show up" sub="Projected beneficiaries and losers" />

                <div className={cn(SECTION_CARD, "p-6 grid grid-cols-1 md:grid-cols-2 gap-6")}>
                  <div>
                    <h4 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-primary mb-3">Beneficiaries</h4>
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
                      <p className="text-[11px] text-on-surface-variant/55">None identified.</p>
                    )}
                  </div>
                  <div>
                    <h4 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-error-dim mb-3">Losers</h4>
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
                      <p className="text-[11px] text-on-surface-variant/55">None identified.</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── STATE B: Low signal ── */}
          {result.analysis && isLowSignal && (
            <div className="space-y-6">
              <div className={cn(SECTION_CARD, "p-6")}>
                <SectionLabel>What Changed</SectionLabel>
                <p className="text-[13px] text-on-surface leading-relaxed">{result.analysis.what_changed}</p>
              </div>

              <div className={cn(SECTION_CARD, "px-5 py-4 flex items-center gap-3")}>
                <div className="w-6 h-6 rounded-full bg-surface-container-highest flex items-center justify-center shrink-0">
                  <AlertTriangle className="h-3.5 w-3.5 text-on-surface-variant/40" />
                </div>
                <div>
                  <p className="text-[12px] font-semibold text-on-surface-variant/80">Insufficient signal</p>
                  <p className="text-[11px] text-on-surface-variant/60 mt-0.5">
                    No clear mechanism, beneficiaries, or losers identified for this event.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* ── ANALYSIS SKELETON (waiting) ── */}
          {!result.analysis && <AnalysisSkeleton />}

          {/* ── TICKER EVIDENCE — raw market reaction (event-window returns) ── */}
          {!result.market ? (
            <div className="space-y-3">
              <Skeleton className="h-3 w-48 bg-surface-container-highest" />
              <div className="grid grid-cols-4 gap-4">
                {[1, 2, 3, 4].map((k) => <Skeleton key={k} className="h-28 rounded-xl bg-surface-container-low" />)}
              </div>
            </div>
          ) : (
            <section className={cn(SECTION_CARD, "p-6")}>
              <div className="flex items-start justify-between mb-5">
                <div>
                  <p className="section-kicker mb-1.5">{MARKET_REACTION_LABEL}</p>
                  <div className="flex items-center gap-2.5">
                    <h3
                      className="text-[13px] font-semibold leading-none tracking-[-0.01em] text-on-surface"
                      style={{ fontFamily: "'Manrope', 'Inter', sans-serif" }}
                    >
                      Tape alignment
                    </h3>
                    <MarketValidationStatus market={result.market} freshness={result.freshness} />
                  </div>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  {!!pendingEventIdRef.current && (
                    <button
                      onClick={refreshMarket}
                      disabled={marketRefreshing}
                      className="flex items-center gap-1.5 text-[11px] text-primary/70 hover:text-primary transition-colors disabled:opacity-40"
                    >
                      <RefreshCw className={cn("w-3 h-3", marketRefreshing && "animate-spin")} />
                      {marketRefreshing ? "Refreshing…" : "Re-run"}
                    </button>
                  )}
                  <span className="text-[11px] text-on-surface-variant/55 tabular-nums">
                    {result.market.tickers.length} ticker{result.market.tickers.length !== 1 && "s"}
                    {result.analysis?.assets_to_watch.length ? <> · {result.analysis.assets_to_watch.join(", ")}</> : null}
                  </span>
                </div>
              </div>
              <p className="mb-4 font-[family-name:var(--so-serif)] text-[12px] font-light italic leading-relaxed text-[var(--so-ink-3)] max-w-2xl">
                {MARKET_REACTION_SUBLABEL}
              </p>
              {(() => {
                const _dn = deriveDegradedNotice(result.market, result.analysis);
                if (!_dn) return null;
                // Surface the scope caveat (deriveDegradedNotice logic is
                // unchanged): a degraded support ratio is computed only on
                // directional / scorable names.
                const caveat = "Support ratio is computed only on directional, scorable names.";
                const detail = _dn.detail ? `${_dn.detail} ${caveat}` : caveat;
                return (
                  <DegradedBanner
                    title={_dn.label}
                    detail={detail}
                    severity={_dn.severity}
                    className="mb-3"
                  />
                );
              })()}
              <MarketSection tickers={result.market.tickers} eventDate={result.event_date ?? undefined} analysis={result.analysis ?? undefined} />
            </section>
          )}

          <ValidationReactionPanel result={result} eventId={pendingEventIdRef.current} />

          {/* ── More analysis ── secondary specialist blocks
              (currency, real yield, shock decomposition, sector
              passthrough, etc.).  Engine reference trails this
              cluster as a collapsible disclosure. */}
          {result.analysis && !isLowSignal && (
            <div className="space-y-8">
              <SectionLead num="06" title="More analysis" sub="Specialist transmission and context blocks" />

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

              {/* Narrative Divergence */}
              {result.analysis.narrative_divergence?.available && (
                <NarrativeDivergenceBlock data={result.analysis.narrative_divergence} />
              )}

              {/* Surprise vs Anticipation Decomposition */}
              {result.analysis.surprise_vs_anticipation && result.analysis.surprise_vs_anticipation.regime && (
                <SurpriseVsAnticipationBlock data={result.analysis.surprise_vs_anticipation} />
              )}

              {/* Terms-of-Trade / External Vulnerability */}
              {result.analysis.terms_of_trade && result.analysis.terms_of_trade.dominant_channel && (
                <TermsOfTradeBlock data={result.analysis.terms_of_trade} />
              )}

              {/* Sector Rotation Impact — direct-hit sectors + downstream
                  cascade.  Sits alongside the other second-order blocks. */}
              {result.analysis.sector_passthrough && result.analysis.sector_passthrough.available && (
                <SectorPassthroughBlock data={result.analysis.sector_passthrough} />
              )}

              {/* Current Account + FX Reserve Stress */}
              {result.analysis.reserve_stress && result.analysis.reserve_stress.dominant_channel && (
                <ReserveStressBlock data={result.analysis.reserve_stress} />
              )}

              {/* Historical Analogs */}
              {result.analysis.historical_analogs && result.analysis.historical_analogs.length > 0 && (
                <HistoricalAnalogsBlock analogs={result.analysis.historical_analogs} />
              )}

            </div>
          )}

          {/* ── FOLLOW-THROUGH — revisit timeline, sequenced after the
              analysis and before the backstage disclosures so the read
              ends on how the thesis actually played out.  Render condition
              unchanged (market present + a saved event to revisit). ── */}
          {result.market && !!pendingEventIdRef.current && (
            <section className={cn(SECTION_CARD, "p-6")}>
              <RevisitTimeline eventId={pendingEventIdRef.current} snapshots={[]} />
            </section>
          )}

          {/* ── BACKSTAGE — collapsed reference disclosures (analyst memo +
              engine-phase fields), framed quietly and trailing the read so
              the thesis narrative stays primary.  The citrine kicker + rule
              renders only on the strong-signal branch (where the memo is
              present), so it can never orphan.  The disclosures' own render
              gates and collapsed-by-default behaviour are unchanged —
              memo: strong-signal only; engine reference: whenever analysis
              is present. ── */}
          {result.analysis && !isLowSignal && (
            <div className="border-t border-[color:var(--so-rule-hi)] pt-6">
              <span className="az-kick">— Backstage · reference</span>
            </div>
          )}
          {result.analysis && !isLowSignal && (
            <ResearchMemoBlock result={result} />
          )}
          {result.analysis && (
            <EnginePhaseSummary analysis={result.analysis} />
          )}
        </div>
      )}
    </div>
  );
}
