import type { AnalyzeResponse } from "./api";
import { MARKET_REACTION_LABEL } from "./claim-copy";

const SEP = "─".repeat(48);

function pctStr(v: number | null | undefined): string {
  if (v == null) return "  —  ";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function volStr(v: number | null | undefined): string {
  if (v == null) return " — ";
  return `${v.toFixed(1)}x`;
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

// ---------------------------------------------------------------------------
// Full analyst memo
// ---------------------------------------------------------------------------

/**
 * Build a plain-text analyst memo from an AnalyzeResponse.
 * Omits any section whose data is empty/null.
 */
export function formatMemo(r: AnalyzeResponse): string {
  const a = r.analysis;
  const lines: string[] = [];

  // ── Header ──────────────────────────────────
  lines.push("SECOND ORDER — RESEARCH NOTE");
  lines.push(SEP);
  lines.push(`Event:  ${r.headline}`);
  if (r.event_date) lines.push(`Date:   ${r.event_date}`);

  // Compact metadata line
  const meta: string[] = [];
  meta.push(r.stage);
  meta.push(r.persistence);
  if (a?.confidence) meta.push(`${a.confidence} confidence`);
  lines.push(`Status: ${meta.join("  ·  ")}`);

  // Freshness
  if (r.freshness) {
    const f = r.freshness;
    const age = f.event_age_days != null ? ` (${f.event_age_days}d old)` : "";
    const frozen = f.is_frozen ? " · frozen" : "";
    lines.push(`Fresh:  ${f.bucket}${age}${frozen}`);
  }

  lines.push("");

  // ── What Changed ────────────────────────────
  if (a?.what_changed) {
    lines.push("WHAT CHANGED");
    lines.push(a.what_changed);
    lines.push("");
  }

  // ── Mechanism ───────────────────────────────
  if (a?.mechanism_summary) {
    lines.push("SECOND-ORDER MECHANISM");
    lines.push(a.mechanism_summary);
    lines.push("");
  }

  // ── Transmission chain ──────────────────────
  if (a?.transmission_chain && a.transmission_chain.length > 0) {
    lines.push("TRANSMISSION");
    lines.push(a.transmission_chain.join(" → "));
    lines.push("");
  }

  // ── Affected assets ─────────────────────────
  const bens = a?.beneficiaries ?? [];
  const losers = a?.losers ?? [];
  const watch = a?.assets_to_watch ?? [];
  if (bens.length || losers.length || watch.length) {
    lines.push("AFFECTED ASSETS");
    if (bens.length) lines.push(`  Beneficiaries : ${bens.join(", ")}`);
    if (losers.length) lines.push(`  Losers        : ${losers.join(", ")}`);
    if (watch.length) lines.push(`  Watch         : ${watch.join(", ")}`);
    lines.push("");
  }

  // ── If Persists ─────────────────────────────
  const ip = a?.if_persists;
  if (ip && (ip.substitution || ip.delayed_winners?.length || ip.delayed_losers?.length)) {
    lines.push("IF PERSISTS");
    if (ip.horizon) lines.push(`  Horizon         : ${ip.horizon}`);
    if (ip.substitution) lines.push(`  Substitution    : ${ip.substitution}`);
    if (ip.delayed_winners?.length)
      lines.push(`  Delayed winners : ${ip.delayed_winners.join(", ")}`);
    if (ip.delayed_losers?.length)
      lines.push(`  Delayed losers  : ${ip.delayed_losers.join(", ")}`);
    lines.push("");
  }

  // ── Shock channels ─────────────────────────
  const sd = a?.shock_decomposition;
  if (sd && sd.available !== false && sd.stale !== true && sd.primary_label) {
    lines.push("SHOCK CHANNELS");
    const rat = sd.rationale ? ` — ${sd.rationale}` : "";
    lines.push(`  Primary: ${sd.primary_label}${rat}`);
    lines.push("");
  }

  // ── Reaction function ──────────────────────
  const rfd = a?.reaction_function_divergence;
  if (rfd && rfd.available !== false && rfd.stale !== true && rfd.implied_label) {
    lines.push("REACTION FUNCTION");
    const parts = [`Implied: ${rfd.implied_label}`];
    if (rfd.priced_label) parts.push(`Priced: ${rfd.priced_label}`);
    if (rfd.divergence_label) parts.push(rfd.divergence_label);
    lines.push(`  ${parts.join("  ·  ")}`);
    if (rfd.rationale) lines.push(`  ${rfd.rationale}`);
    lines.push("");
  }

  // ── Historical analogs ─────────────────────
  const analogs = a?.historical_analogs;
  if (analogs && analogs.length > 0) {
    lines.push("HISTORICAL ANALOGS");
    for (const h of analogs.slice(0, 3)) {
      const date = h.event_date ? ` (${h.event_date})` : "";
      const decay = h.decay ? ` — ${h.decay}` : "";
      lines.push(`  ${h.headline}${date}${decay}`);
    }
    lines.push("");
  }

  // ── Market reaction (raw) ───────────────────
  const tickers = r.market?.tickers ?? [];
  const mNote = r.market?.note;
  if (tickers.length > 0) {
    lines.push(MARKET_REACTION_LABEL.toUpperCase());
    lines.push("Raw event-window returns (1d/5d/20d) — not benchmark-adjusted.");
    if (mNote) {
      lines.push(mNote);
      lines.push("");
    }
    lines.push(
      `  ${"Ticker".padEnd(8)} ${"Role".padEnd(13)} ${"1d".padStart(8)}  ${"5d".padStart(8)}  ${"20d".padStart(8)}  ${"Vol".padStart(5)}  Signal`,
    );
    lines.push(
      `  ${"─".repeat(8)} ${"─".repeat(13)} ${"─".repeat(8)}  ${"─".repeat(8)}  ${"─".repeat(8)}  ${"─".repeat(5)}  ${"─".repeat(12)}`,
    );
    for (const t of tickers) {
      const dir = t.direction_tag ?? "pending";
      lines.push(
        `  ${t.symbol.padEnd(8)} ${(t.role ?? "").padEnd(13)} ${pctStr(t.return_1d).padStart(8)}  ${pctStr(t.return_5d).padStart(8)}  ${pctStr(t.return_20d).padStart(8)}  ${volStr(t.volume_ratio).padStart(5)}  ${dir}`,
      );
    }
    lines.push("");
  }

  // ── Footer ──────────────────────────────────
  lines.push(SEP);

  if (r.market?.data_quality === "degraded") {
    const note = r.market.data_quality_note ?? "Some data may be incomplete";
    lines.push(`⚠ ${note}`);
  }

  const now = new Date().toISOString().slice(0, 16).replace("T", " ");
  lines.push(`Generated ${now} UTC`);

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Markdown memo — same data as formatMemo(), rendered as Markdown
// ---------------------------------------------------------------------------

/**
 * Build a Markdown research memo from an AnalyzeResponse.
 * Mirrors the section order of formatMemo() but uses Markdown syntax.
 */
export function formatMemoMarkdown(r: AnalyzeResponse): string {
  const a = r.analysis;
  const lines: string[] = [];

  // Header
  lines.push(`# ${r.headline}`);
  lines.push("");
  const meta: string[] = [];
  if (r.event_date) meta.push(`**Date:** ${r.event_date}`);
  const stageParts = [r.stage, r.persistence, a?.confidence ? `${a.confidence} confidence` : null]
    .filter(Boolean)
    .join(" · ");
  if (stageParts) meta.push(`**Stage:** ${stageParts}`);
  if (meta.length) { lines.push(meta.join(" · ")); lines.push(""); }

  if (a?.what_changed) {
    lines.push("## What Changed");
    lines.push("");
    lines.push(a.what_changed);
    lines.push("");
  }

  if (a?.mechanism_summary) {
    lines.push("## Mechanism");
    lines.push("");
    lines.push(a.mechanism_summary);
    lines.push("");
  }

  if (a?.transmission_chain && a.transmission_chain.length > 0) {
    lines.push("## Transmission");
    lines.push("");
    lines.push(a.transmission_chain.join(" → "));
    lines.push("");
  }

  const bens = a?.beneficiaries ?? [];
  const losers = a?.losers ?? [];
  const watch = a?.assets_to_watch ?? [];
  if (bens.length || losers.length || watch.length) {
    lines.push("## Affected Assets");
    lines.push("");
    if (bens.length) lines.push(`**Beneficiaries:** ${bens.join(", ")}`);
    if (losers.length) lines.push(`**Losers:** ${losers.join(", ")}`);
    if (watch.length) lines.push(`**Watch:** ${watch.join(", ")}`);
    lines.push("");
  }

  const ip = a?.if_persists;
  if (ip && (ip.substitution || ip.delayed_winners?.length || ip.delayed_losers?.length)) {
    lines.push("## If Persists");
    lines.push("");
    if (ip.horizon) lines.push(`**Horizon:** ${ip.horizon}`);
    if (ip.substitution) lines.push(`**Substitution:** ${ip.substitution}`);
    if (ip.delayed_winners?.length) lines.push(`**Delayed winners:** ${ip.delayed_winners.join(", ")}`);
    if (ip.delayed_losers?.length) lines.push(`**Delayed losers:** ${ip.delayed_losers.join(", ")}`);
    lines.push("");
  }

  const sd = a?.shock_decomposition;
  if (sd && sd.available !== false && sd.stale !== true && sd.primary_label) {
    lines.push("## Shock Channels");
    lines.push("");
    lines.push(`**Primary:** ${sd.primary_label}${sd.rationale ? ` — ${sd.rationale}` : ""}`);
    lines.push("");
  }

  const rfd = a?.reaction_function_divergence;
  if (rfd && rfd.available !== false && rfd.stale !== true && rfd.implied_label) {
    lines.push("## Reaction Function");
    lines.push("");
    const parts = [`**Implied:** ${rfd.implied_label}`];
    if (rfd.priced_label) parts.push(`**Priced:** ${rfd.priced_label}`);
    if (rfd.divergence_label) parts.push(`**Divergence:** ${rfd.divergence_label}`);
    lines.push(parts.join(" · "));
    if (rfd.rationale) { lines.push(""); lines.push(rfd.rationale); }
    lines.push("");
  }

  const analogs = a?.historical_analogs;
  if (analogs && analogs.length > 0) {
    lines.push("## Historical Analogs");
    lines.push("");
    for (const h of analogs.slice(0, 3)) {
      const date = h.event_date ? ` (${h.event_date})` : "";
      const decay = h.decay ? ` — ${h.decay}` : "";
      lines.push(`- ${h.headline}${date}${decay}`);
    }
    lines.push("");
  }

  const tickers = r.market?.tickers ?? [];
  if (tickers.length > 0) {
    lines.push(`## ${MARKET_REACTION_LABEL}`);
    lines.push("");
    lines.push("_Raw event-window returns (1d/5d/20d) — not benchmark-adjusted._");
    lines.push("");
    if (r.market?.note) { lines.push(`> ${r.market.note}`); lines.push(""); }
    lines.push("| Ticker | Role | 1d | 5d | 20d | Signal |");
    lines.push("|--------|------|---:|---:|----:|--------|");
    for (const t of tickers) {
      lines.push(
        `| ${t.symbol} | ${t.role ?? ""} | ${pctStr(t.return_1d).trim()} | ${pctStr(t.return_5d).trim()} | ${pctStr(t.return_20d).trim()} | ${t.direction_tag ?? "pending"} |`,
      );
    }
    lines.push("");
  }

  lines.push("---");
  const now = new Date().toISOString().slice(0, 16).replace("T", " ");
  lines.push(`*Generated ${now} UTC · Second Order*`);

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Compact blurb for chat / Slack / quick sharing
// ---------------------------------------------------------------------------

/**
 * Build a 3-5 line compact summary for chat or quick sharing.
 */
export function formatBlurb(r: AnalyzeResponse): string {
  const a = r.analysis;
  const lines: string[] = [];

  // Line 1: headline + metadata
  const conf = a?.confidence ? ` (${a.confidence} confidence)` : "";
  lines.push(`${r.headline} — ${r.stage}${conf}`);

  // Line 2: mechanism
  if (a?.mechanism_summary) {
    lines.push(`Mechanism: ${truncate(a.mechanism_summary, 120)}`);
  }

  // Line 3: tickers — beneficiaries ▲ and losers ▼
  const tickers = r.market?.tickers ?? [];
  const benTickers = tickers
    .filter((t) => t.role === "beneficiary" && t.return_5d != null)
    .slice(0, 3);
  const loseTickers = tickers
    .filter((t) => t.role === "loser" && t.return_5d != null)
    .slice(0, 3);

  const parts: string[] = [];
  if (benTickers.length > 0) {
    parts.push("▲ " + benTickers.map((t) => `${t.symbol} ${pctStr(t.return_5d!).trim()}`).join(", "));
  }
  if (loseTickers.length > 0) {
    parts.push("▼ " + loseTickers.map((t) => `${t.symbol} ${pctStr(t.return_5d!).trim()}`).join(", "));
  }
  if (parts.length > 0) {
    lines.push(parts.join("  "));
  }

  // Line 4: timestamp
  const now = new Date().toISOString().slice(0, 16).replace("T", " ");
  lines.push(`Generated ${now} UTC`);

  return lines.join("\n");
}
