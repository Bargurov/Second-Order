/**
 * live-brief.tsx — the local-first Live Event Brief surface (LEB-0).
 *
 * An operator structures a real live event into sourced facts,
 * interpretations, unknowns, competing mechanisms, asset roles, timestamped
 * market reactions, historical context, falsifiers and 1d/5d/20d follow-up —
 * without any provider call, backend write, or database mutation.  Everything
 * persists to browser ``localStorage`` under the versioned
 * ``live-event-brief-v1`` contract and survives a page refresh.
 *
 * Product boundary: the fixed non-claim (see NON_CLAIM) bounds what a brief may
 * assert — it is structured decision support only.  No field carries a
 * directional or sizing view; historical evidence stays descriptive context.
 *
 * Testability: all state logic lives in the pure ``@/lib/live-brief`` layer.
 * The component is a thin shell that renders under the project's no-jsdom
 * render-smoke pattern via documented ``initial*`` seams; storage and the clock
 * are only touched inside event handlers and a persist effect (never during a
 * render), so a static render is side-effect free.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section-header";
import { StateBadge, type BadgeVariant } from "@/components/ui/state-badge";
import { LiveBriefHistoricalContext, type HistoricalPanel } from "@/components/ui/live-brief-historical-context";
import {
  ASSET_ROLES,
  COMPARABLE_COHORTS,
  ENTRY_TYPES,
  FALSIFIER_STATUSES,
  FOLLOW_UP_STAGES,
  FOLLOW_UP_STATUSES,
  HYPOTHESIS_STATES,
  NON_CLAIM,
  REACTION_HORIZONS,
  STAGE_LABELS,
  STAGES,
  type AssetRole,
  type Brief,
  type ComparableCohort,
  type EntryType,
  type FalsifierStatus,
  type FollowUpStage,
  type FollowUpStatus,
  type HypothesisState,
  type ReactionHorizon,
  type Stage,
  type TypedEntry,
} from "@/lib/live-brief/types";
import {
  addAssetRole,
  addFalsifier,
  addFollowUp,
  addHypothesis,
  addMarketReaction,
  addTypedEntry,
  appendRevision,
  createBrief,
  overdueFollowUps,
  patchBrief,
  patchItem,
  removeItem,
  setStage,
} from "@/lib/live-brief/operations";
import {
  exportBriefJson,
  exportBriefMarkdown,
  importBriefJson,
} from "@/lib/live-brief/export";
import {
  loadBriefs,
  removeBrief,
  saveBriefs,
  upsertBrief,
} from "@/lib/live-brief/storage";

// ---------------------------------------------------------------------------
// Browser-only helpers (called from handlers, never during a render)
// ---------------------------------------------------------------------------

function nowIso(): string {
  return new Date().toISOString();
}

function genId(prefix: string): string {
  const rand =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2);
  return `${prefix}-${rand}`;
}

function downloadText(filename: string, text: string, mime: string): void {
  if (typeof document === "undefined" || typeof URL === "undefined" || !URL.createObjectURL) return;
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Small styled primitives
// ---------------------------------------------------------------------------

const INPUT =
  "w-full rounded-md border border-border bg-background/60 px-2 py-1 text-xs text-foreground " +
  "placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/80">
        {label}
      </span>
      {children}
    </label>
  );
}

function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={INPUT} />;
}

function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} rows={props.rows ?? 2} className={INPUT} />;
}

function SelectInput({
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...props} className={INPUT}>
      {children}
    </select>
  );
}

function GhostButton({
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...props}
      className={
        "rounded-md border border-border bg-secondary px-2.5 py-1 text-xs font-medium text-foreground " +
        "transition-colors hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50 " +
        (props.className ?? "")
      }
    >
      {children}
    </button>
  );
}

function RemoveButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:border-destructive/40 hover:text-destructive"
    >
      Remove
    </button>
  );
}

function SectionCard({
  kicker,
  title,
  subtitle,
  action,
  section,
  children,
}: {
  kicker: string;
  title: string;
  subtitle?: string;
  action?: ReactNode;
  section?: string;
  children: ReactNode;
}) {
  return (
    <Card className="overflow-hidden border-border/60" data-section={section}>
      <CardHeader className="border-b border-border/40 bg-secondary/40">
        <SectionHeader kicker={kicker} title={title} subtitle={subtitle} action={action} />
      </CardHeader>
      <CardContent className="flex flex-col gap-3 pt-3">{children}</CardContent>
    </Card>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-xs italic text-muted-foreground">{children}</p>;
}

const ENTRY_BADGE: Record<EntryType, BadgeVariant> = {
  FACT: "neutral",
  INTERPRETATION: "pending",
  UNKNOWN: "warning",
};

function statusBadgeVariant(status: FalsifierStatus): BadgeVariant {
  if (status === "TRIGGERED") return "stress";
  if (status === "NOT_TRIGGERED") return "neutral";
  return "pending";
}

// ---------------------------------------------------------------------------
// Non-claim banner (permanent)
// ---------------------------------------------------------------------------

function NonClaimBanner() {
  return (
    <div
      role="note"
      className="rounded-lg border border-border/70 bg-secondary/50 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground"
      data-testid="non-claim"
    >
      {NON_CLAIM}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Brief list + create + empty state
// ---------------------------------------------------------------------------

function BriefList({
  briefs,
  activeId,
  onSelect,
  onCreate,
}: {
  briefs: Brief[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  return (
    <Card className="overflow-hidden border-border/60">
      <CardHeader className="flex-row items-center justify-between border-b border-border/40 bg-secondary/40">
        <SectionHeader kicker="Local briefs" title="Your briefs" />
        <GhostButton onClick={onCreate} data-testid="create-brief">
          + New brief
        </GhostButton>
      </CardHeader>
      <CardContent className="pt-3">
        {briefs.length === 0 ? (
          <Empty>No briefs yet. Create one to start structuring a live event.</Empty>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {briefs.map((b) => {
              const active = b.brief_id === activeId;
              return (
                <li key={b.brief_id}>
                  <button
                    type="button"
                    onClick={() => onSelect(b.brief_id)}
                    aria-current={active ? "true" : undefined}
                    className={
                      "flex w-full items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-left text-xs transition-colors " +
                      (active
                        ? "border-primary/40 bg-primary/10 text-foreground"
                        : "border-border bg-background/40 text-muted-foreground hover:text-foreground")
                    }
                  >
                    <span className="min-w-0 truncate font-medium">{b.title || "Untitled brief"}</span>
                    <span className="shrink-0 font-num text-[10px] text-muted-foreground">
                      {b.current_stage}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function EmptyEditor({ onCreate }: { onCreate: () => void }) {
  return (
    <Card className="empty-surface flex min-h-[280px] flex-col items-center justify-center gap-3 border-dashed p-8 text-center">
      <p className="font-headline text-sm font-semibold text-foreground">No brief selected</p>
      <p className="max-w-md text-xs leading-relaxed text-muted-foreground">
        A Live Event Brief structures a real event into sourced facts, competing mechanisms, asset
        roles, timestamped reactions, falsifiers and 1d/5d/20d follow-up — locally, with no provider
        cost. Create one to begin.
      </p>
      <GhostButton onClick={onCreate} data-testid="create-brief-empty">
        + New brief
      </GhostButton>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Editor header — stage + as-of
// ---------------------------------------------------------------------------

function EditorHeader({
  brief,
  onStage,
  onDelete,
}: {
  brief: Brief;
  onStage: (s: Stage) => void;
  onDelete: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  return (
    <Card className="overflow-hidden border-border/60">
      <CardContent className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="section-kicker mb-1">Live event brief</p>
            <h1 className="font-headline text-lg font-semibold leading-tight tracking-[-0.01em] text-foreground">
              {brief.title || "Untitled brief"}
            </h1>
            <p className="mt-1 font-num text-[11px] text-muted-foreground">
              Last updated {brief.updated_at} · created {brief.created_at}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <StateBadge variant="live" label={`Stage · ${STAGE_LABELS[brief.current_stage]}`} />
            {confirming ? (
              <span className="flex items-center gap-1.5">
                <span className="text-[11px] text-muted-foreground">Delete this brief?</span>
                <button
                  type="button"
                  onClick={onDelete}
                  data-testid="confirm-delete"
                  className="rounded-md border border-destructive/40 px-2 py-0.5 text-[11px] font-medium text-destructive hover:bg-destructive/10"
                >
                  Confirm
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
                >
                  Cancel
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setConfirming(true)}
                data-testid="delete-brief"
                className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:border-destructive/40 hover:text-destructive"
              >
                Delete
              </button>
            )}
          </div>
        </div>

        <fieldset className="flex flex-wrap items-end gap-3 border-0 p-0">
          <legend className="sr-only">Review stage</legend>
          <Field label="Review stage (review step, not outcome)">
            <SelectInput
              value={brief.current_stage}
              onChange={(e) => onStage(e.target.value as Stage)}
              data-testid="stage-select"
            >
              {STAGES.map((s) => (
                <option key={s} value={s}>
                  {STAGE_LABELS[s]}
                </option>
              ))}
            </SelectInput>
          </Field>
        </fieldset>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Event identity + sources
// ---------------------------------------------------------------------------

function IdentitySection({
  brief,
  onPatch,
  onAddSource,
  onRemoveSource,
}: {
  brief: Brief;
  onPatch: (patch: Partial<Brief>) => void;
  onAddSource: (label: string, url: string, note: string) => void;
  onRemoveSource: (id: string) => void;
}) {
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  return (
    <SectionCard kicker="Event identity" title="Identity & official sources" subtitle="Event date and market-session timestamp stay separate.">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Event title">
          <TextInput value={brief.title} onChange={(e) => onPatch({ title: e.target.value })} placeholder="e.g. March FOMC rate decision" />
        </Field>
        <Field label="Family">
          <TextInput value={brief.event_family} onChange={(e) => onPatch({ event_family: e.target.value })} placeholder="e.g. FOMC" />
        </Field>
        <Field label="Event type">
          <TextInput value={brief.event_type} onChange={(e) => onPatch({ event_type: e.target.value })} placeholder="e.g. Scheduled policy decision" />
        </Field>
        <Field label="Event date">
          <TextInput value={brief.event_date} onChange={(e) => onPatch({ event_date: e.target.value })} placeholder="YYYY-MM-DD" />
        </Field>
        <Field label="Scheduled / observed timestamp">
          <TextInput value={brief.scheduled_timestamp} onChange={(e) => onPatch({ scheduled_timestamp: e.target.value })} placeholder="market-session timestamp" />
        </Field>
        <Field label="Timezone">
          <TextInput value={brief.timezone} onChange={(e) => onPatch({ timezone: e.target.value })} placeholder="e.g. America/New_York" />
        </Field>
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/80">
          Official / primary source references
        </p>
        {brief.source_references.length === 0 ? (
          <Empty>No sources attached.</Empty>
        ) : (
          <ul className="flex flex-col gap-1">
            {brief.source_references.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-2 rounded-md border border-border bg-background/40 px-2 py-1 text-xs">
                <span className="min-w-0 truncate">
                  <span className="font-medium text-foreground">{s.label || "(unlabelled)"}</span>
                  {s.url ? <span className="text-muted-foreground"> · {s.url}</span> : null}
                  {s.note ? <span className="text-muted-foreground/80"> — {s.note}</span> : null}
                </span>
                <RemoveButton onClick={() => onRemoveSource(s.id)} label={`Remove source ${s.label}`} />
              </li>
            ))}
          </ul>
        )}
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
          <Field label="Label"><TextInput value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
          <Field label="URL"><TextInput value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
          <Field label="Note"><TextInput value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <div className="flex items-end">
            <GhostButton
              onClick={() => {
                if (!label.trim()) return;
                onAddSource(label, url, note);
                setLabel("");
                setUrl("");
                setNote("");
              }}
            >
              + Add source
            </GhostButton>
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Typed research entries (facts + unknowns)
// ---------------------------------------------------------------------------

function TypedEntriesSection({
  kicker,
  title,
  subtitle,
  section,
  entries,
  defaultType,
  onAdd,
  onRemove,
}: {
  kicker: string;
  title: string;
  subtitle: string;
  section: string;
  entries: TypedEntry[];
  defaultType: EntryType;
  onAdd: (type: EntryType, text: string, sourceRef: string, sourceNote: string) => void;
  onRemove: (id: string) => void;
}) {
  const [type, setType] = useState<EntryType>(defaultType);
  const [text, setText] = useState("");
  const [sourceRef, setSourceRef] = useState("");
  const [sourceNote, setSourceNote] = useState("");
  const needsSource = type === "FACT" && !sourceRef.trim() && !sourceNote.trim();

  return (
    <SectionCard kicker={kicker} title={title} subtitle={subtitle} section={section}>
      {entries.length === 0 ? (
        <Empty>None recorded.</Empty>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {entries.map((e) => (
            <li key={e.id} className="flex items-start justify-between gap-2 rounded-md border border-border bg-background/40 px-2.5 py-1.5">
              <div className="min-w-0">
                <div className="mb-0.5 flex items-center gap-2">
                  <StateBadge variant={ENTRY_BADGE[e.type]} label={e.type} />
                  <span className="font-num text-[10px] text-muted-foreground">as of {e.as_of}</span>
                </div>
                <p className="text-xs leading-relaxed text-foreground/90">{e.text}</p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {e.source_reference
                    ? `Source: ${e.source_reference}`
                    : e.source_note
                      ? `Source note: ${e.source_note}`
                      : e.type === "FACT"
                        ? "Source: not attached"
                        : ""}
                </p>
              </div>
              <RemoveButton onClick={() => onRemove(e.id)} label="Remove entry" />
            </li>
          ))}
        </ul>
      )}

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-5">
        <Field label="Type">
          <SelectInput value={type} onChange={(ev) => setType(ev.target.value as EntryType)}>
            {ENTRY_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </SelectInput>
        </Field>
        <div className="sm:col-span-2">
          <Field label="Note"><TextInput value={text} onChange={(e) => setText(e.target.value)} placeholder="one note, one type" /></Field>
        </div>
        <Field label="Source ref"><TextInput value={sourceRef} onChange={(e) => setSourceRef(e.target.value)} /></Field>
        <Field label="Source note (if none yet)"><TextInput value={sourceNote} onChange={(e) => setSourceNote(e.target.value)} /></Field>
      </div>
      {needsSource ? (
        <p className="text-[11px] text-destructive">A FACT needs a source reference or an explicit note that the source is not yet attached.</p>
      ) : null}
      <div>
        <GhostButton
          disabled={!text.trim() || needsSource}
          onClick={() => {
            onAdd(type, text, sourceRef, sourceNote);
            setText("");
            setSourceRef("");
            setSourceNote("");
          }}
        >
          + Add {defaultType === "UNKNOWN" ? "unknown" : "entry"}
        </GhostButton>
      </div>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// What changed
// ---------------------------------------------------------------------------

function WhatChangedSection({ brief, onPatch }: { brief: Brief; onPatch: (patch: Partial<Brief>) => void }) {
  const d = brief.delta_vs_prior;
  const set = (k: keyof typeof d, v: string) => onPatch({ delta_vs_prior: { ...d, [k]: v } });
  return (
    <SectionCard kicker="Delta" title="What changed?" subtitle="Operator-written. The delta is never generated automatically.">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Previous state"><TextArea value={d.previous_state} onChange={(e) => set("previous_state", e.target.value)} /></Field>
        <Field label="New information"><TextArea value={d.new_information} onChange={(e) => set("new_information", e.target.value)} /></Field>
        <Field label="Unchanged information"><TextArea value={d.unchanged_information} onChange={(e) => set("unchanged_information", e.target.value)} /></Field>
        <Field label="Unresolved information"><TextArea value={d.unresolved_information} onChange={(e) => set("unresolved_information", e.target.value)} /></Field>
      </div>
      <Field label="Operator delta summary"><TextArea value={d.operator_delta_summary} onChange={(e) => set("operator_delta_summary", e.target.value)} /></Field>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Competing mechanism hypotheses (uniform, no winner)
// ---------------------------------------------------------------------------

function HypothesesSection({
  brief,
  onAdd,
  onState,
  onRemove,
}: {
  brief: Brief;
  onAdd: (name: string, path: string) => void;
  onState: (id: string, state: HypothesisState) => void;
  onRemove: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const active = brief.mechanism_hypotheses.filter((h) => h.current_state !== "FALSIFIED").length;
  const atCap = active >= 3;

  return (
    <SectionCard
      kicker="Competing mechanisms"
      section="hypotheses"
      title="Mechanism hypotheses"
      subtitle="Up to three active. Presented side by side — none is marked a winner."
      action={<span className="font-num text-[11px] text-muted-foreground">{active}/3 active</span>}
    >
      {brief.mechanism_hypotheses.length === 0 ? (
        <Empty>No hypotheses yet.</Empty>
      ) : (
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
          {brief.mechanism_hypotheses.map((h) => (
            <div key={h.hypothesis_id} className="flex flex-col gap-2 rounded-lg border border-border bg-background/40 p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="min-w-0 text-xs font-semibold text-foreground">{h.name || "(unnamed)"}</p>
                <StateBadge variant="neutral" label={h.current_state} />
              </div>
              <p className="text-[11px] leading-relaxed text-muted-foreground">{h.mechanism_path}</p>
              <div className="flex items-center justify-between gap-2">
                <label className="flex items-center gap-1 text-[10px] uppercase tracking-[0.08em] text-muted-foreground/80">
                  <span className="sr-only">Hypothesis state for {h.name}</span>
                  <SelectInput
                    value={h.current_state}
                    onChange={(e) => onState(h.hypothesis_id, e.target.value as HypothesisState)}
                    aria-label={`State for ${h.name || "hypothesis"}`}
                  >
                    {HYPOTHESIS_STATES.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </SelectInput>
                </label>
                <RemoveButton onClick={() => onRemove(h.hypothesis_id)} label={`Remove hypothesis ${h.name}`} />
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-5">
        <div className="sm:col-span-2">
          <Field label="Hypothesis name"><TextInput value={name} onChange={(e) => setName(e.target.value)} /></Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Mechanism path"><TextInput value={path} onChange={(e) => setPath(e.target.value)} placeholder="trigger → channel → asset" /></Field>
        </div>
        <div className="flex items-end">
          <GhostButton
            disabled={!name.trim() || atCap}
            onClick={() => {
              onAdd(name, path);
              setName("");
              setPath("");
            }}
          >
            + Add hypothesis
          </GhostButton>
        </div>
      </div>
      {atCap ? <p className="text-[11px] text-muted-foreground">Three active hypotheses already. Falsify or remove one to add another.</p> : null}
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Asset roles + market reactions
// ---------------------------------------------------------------------------

function AssetRolesSection({
  brief,
  onAdd,
  onRemove,
}: {
  brief: Brief;
  onAdd: (asset: string, role: AssetRole, benchmark: string, lens: string, channel: string, window: string, basis: string, limitations: string) => void;
  onRemove: (id: string) => void;
}) {
  const [asset, setAsset] = useState("");
  const [role, setRole] = useState<AssetRole>("PRIMARY");
  const [benchmark, setBenchmark] = useState("");
  const [lens, setLens] = useState("");
  const [channel, setChannel] = useState("");
  const [window, setWindow] = useState("");
  const [basis, setBasis] = useState("");
  const [limitations, setLimitations] = useState("");

  return (
    <SectionCard section="assets" kicker="Asset-role map" title="Assets & expected channels" subtitle="Descriptive mapping of assets to research roles and expected channels.">
      {brief.asset_roles.length === 0 ? (
        <Empty>No assets mapped.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead>
              <tr className="border-b border-border text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
                <th scope="col" className="py-1 pr-2">Asset</th>
                <th scope="col" className="py-1 pr-2">Role</th>
                <th scope="col" className="py-1 pr-2">Benchmark</th>
                <th scope="col" className="py-1 pr-2">Sector / lens</th>
                <th scope="col" className="py-1 pr-2">Expected channel</th>
                <th scope="col" className="py-1 pr-2">Basis</th>
                <th scope="col" className="py-1 pr-2">Limitations</th>
                <th scope="col" className="py-1 pr-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {brief.asset_roles.map((a) => (
                <tr key={a.id} className="border-b border-border/40 align-top">
                  <td className="py-1 pr-2 font-num font-medium text-foreground">{a.asset}</td>
                  <td className="py-1 pr-2">{a.role}</td>
                  <td className="py-1 pr-2 text-muted-foreground">{a.benchmark || "—"}</td>
                  <td className="py-1 pr-2 text-muted-foreground">{a.sector_or_relative_lens || "—"}</td>
                  <td className="py-1 pr-2 text-muted-foreground">{a.expected_channel || "—"}</td>
                  <td className="py-1 pr-2 text-muted-foreground">{a.basis || "—"}</td>
                  <td className="py-1 pr-2 text-muted-foreground">{a.limitations || "—"}</td>
                  <td className="py-1 pr-2"><RemoveButton onClick={() => onRemove(a.id)} label={`Remove asset ${a.asset}`} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Field label="Asset"><TextInput value={asset} onChange={(e) => setAsset(e.target.value)} /></Field>
        <Field label="Role">
          <SelectInput value={role} onChange={(e) => setRole(e.target.value as AssetRole)}>
            {ASSET_ROLES.map((r) => (<option key={r} value={r}>{r}</option>))}
          </SelectInput>
        </Field>
        <Field label="Benchmark"><TextInput value={benchmark} onChange={(e) => setBenchmark(e.target.value)} /></Field>
        <Field label="Sector / lens"><TextInput value={lens} onChange={(e) => setLens(e.target.value)} /></Field>
        <Field label="Expected channel"><TextInput value={channel} onChange={(e) => setChannel(e.target.value)} /></Field>
        <Field label="Window"><TextInput value={window} onChange={(e) => setWindow(e.target.value)} /></Field>
        <Field label="Basis"><TextInput value={basis} onChange={(e) => setBasis(e.target.value)} /></Field>
        <Field label="Limitations"><TextInput value={limitations} onChange={(e) => setLimitations(e.target.value)} /></Field>
      </div>
      <div>
        <GhostButton
          disabled={!asset.trim()}
          onClick={() => {
            onAdd(asset, role, benchmark, lens, channel, window, basis, limitations);
            setAsset(""); setBenchmark(""); setLens(""); setChannel(""); setWindow(""); setBasis(""); setLimitations("");
          }}
        >
          + Add asset
        </GhostButton>
      </div>
    </SectionCard>
  );
}

function ReactionsSection({
  brief,
  onAdd,
  onRemove,
}: {
  brief: Brief;
  onAdd: (horizon: ReactionHorizon, value: number | null, unit: string, basis: string, window: string, source: string) => void;
  onRemove: (id: string) => void;
}) {
  const [horizon, setHorizon] = useState<ReactionHorizon>("1d");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("%");
  const [basis, setBasis] = useState("");
  const [window, setWindow] = useState("");
  const [source, setSource] = useState("");
  const numeric = value.trim() !== "" && Number.isFinite(Number(value));
  const missingBasis = numeric && !basis.trim();

  return (
    <SectionCard section="reactions" kicker="Market reaction" title="Reaction observations" subtitle="Manual entry. A missing value stays visible as unavailable and is never auto-classified.">
      {brief.market_reactions.length === 0 ? (
        <Empty>No observations recorded.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-xs">
            <thead>
              <tr className="border-b border-border text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
                <th scope="col" className="py-1 pr-2">Horizon</th>
                <th scope="col" className="py-1 pr-2">Value</th>
                <th scope="col" className="py-1 pr-2">Basis</th>
                <th scope="col" className="py-1 pr-2">Window</th>
                <th scope="col" className="py-1 pr-2">Source</th>
                <th scope="col" className="py-1 pr-2">As of</th>
                <th scope="col" className="py-1 pr-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {brief.market_reactions.map((m) => (
                <tr key={m.id} className="border-b border-border/40">
                  <td className="py-1 pr-2 font-medium text-foreground">{m.horizon}</td>
                  <td className="py-1 pr-2 font-num">
                    {m.value === null ? (
                      <span className="italic text-muted-foreground">unavailable</span>
                    ) : (
                      <span>{m.value}{m.unit ? ` ${m.unit}` : ""}</span>
                    )}
                  </td>
                  <td className="py-1 pr-2 text-muted-foreground">{m.basis || "—"}</td>
                  <td className="py-1 pr-2 text-muted-foreground">{m.window || "—"}</td>
                  <td className="py-1 pr-2 text-muted-foreground">{m.source || "—"}</td>
                  <td className="py-1 pr-2 font-num text-[10px] text-muted-foreground">{m.as_of}</td>
                  <td className="py-1 pr-2"><RemoveButton onClick={() => onRemove(m.id)} label={`Remove ${m.horizon} reaction`} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Field label="Horizon">
          <SelectInput value={horizon} onChange={(e) => setHorizon(e.target.value as ReactionHorizon)}>
            {REACTION_HORIZONS.map((h) => (<option key={h} value={h}>{h}</option>))}
          </SelectInput>
        </Field>
        <Field label="Value (blank = unavailable)"><TextInput value={value} onChange={(e) => setValue(e.target.value)} inputMode="decimal" /></Field>
        <Field label="Unit"><TextInput value={unit} onChange={(e) => setUnit(e.target.value)} /></Field>
        <Field label="Basis (required if numeric)"><TextInput value={basis} onChange={(e) => setBasis(e.target.value)} /></Field>
        <Field label="Window"><TextInput value={window} onChange={(e) => setWindow(e.target.value)} /></Field>
        <Field label="Source"><TextInput value={source} onChange={(e) => setSource(e.target.value)} /></Field>
      </div>
      {missingBasis ? <p className="text-[11px] text-destructive">A numeric observation must state its basis.</p> : null}
      <div>
        <GhostButton
          disabled={missingBasis}
          onClick={() => {
            const v = value.trim() === "" ? null : Number(value);
            onAdd(horizon, v, unit, basis, window, source);
            setValue(""); setBasis(""); setWindow(""); setSource("");
          }}
        >
          + Add observation
        </GhostButton>
      </div>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Falsifiers (always visible; triggered never hidden)
// ---------------------------------------------------------------------------

function FalsifiersSection({
  brief,
  onAdd,
  onStatus,
  onRemove,
}: {
  brief: Brief;
  onAdd: (statement: string, linked: string, observable: string, window: string) => void;
  onStatus: (id: string, status: FalsifierStatus) => void;
  onRemove: (id: string) => void;
}) {
  const [statement, setStatement] = useState("");
  const [linked, setLinked] = useState("");
  const [observable, setObservable] = useState("");
  const [window, setWindow] = useState("");

  return (
    <SectionCard section="falsifiers" kicker="Falsifiers" title="Falsifiers" subtitle="Always visible. A triggered falsifier is never hidden.">
      {brief.falsifiers.length === 0 ? (
        <Empty>No falsifiers defined.</Empty>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {brief.falsifiers.map((f) => (
            <li key={f.falsifier_id} className="flex items-start justify-between gap-2 rounded-md border border-border bg-background/40 px-2.5 py-1.5">
              <div className="min-w-0">
                <div className="mb-0.5 flex flex-wrap items-center gap-2">
                  <StateBadge variant={statusBadgeVariant(f.status)} label={f.status} />
                  {f.linked_hypothesis ? <span className="font-num text-[10px] text-muted-foreground">→ {f.linked_hypothesis}</span> : null}
                  <span className="font-num text-[10px] text-muted-foreground">as of {f.as_of}</span>
                </div>
                <p className="text-xs leading-relaxed text-foreground/90">{f.statement}</p>
                {f.observable ? <p className="text-[11px] text-muted-foreground">Observable: {f.observable} · window {f.evaluation_window || "—"}</p> : null}
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <SelectInput
                  value={f.status}
                  onChange={(e) => onStatus(f.falsifier_id, e.target.value as FalsifierStatus)}
                  aria-label={`Status for falsifier: ${f.statement}`}
                >
                  {FALSIFIER_STATUSES.map((s) => (<option key={s} value={s}>{s}</option>))}
                </SelectInput>
                <RemoveButton onClick={() => onRemove(f.falsifier_id)} label="Remove falsifier" />
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
        <div className="sm:col-span-2"><Field label="Statement"><TextInput value={statement} onChange={(e) => setStatement(e.target.value)} /></Field></div>
        <Field label="Linked hypothesis">
          <SelectInput value={linked} onChange={(e) => setLinked(e.target.value)}>
            <option value="">(none)</option>
            {brief.mechanism_hypotheses.map((h) => (<option key={h.hypothesis_id} value={h.hypothesis_id}>{h.name || h.hypothesis_id}</option>))}
          </SelectInput>
        </Field>
        <Field label="Observable"><TextInput value={observable} onChange={(e) => setObservable(e.target.value)} /></Field>
        <Field label="Evaluation window"><TextInput value={window} onChange={(e) => setWindow(e.target.value)} /></Field>
      </div>
      <div>
        <GhostButton
          disabled={!statement.trim()}
          onClick={() => {
            onAdd(statement, linked, observable, window);
            setStatement(""); setLinked(""); setObservable(""); setWindow("");
          }}
        >
          + Add falsifier
        </GhostButton>
      </div>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Follow-up plan (overdue surfaced)
// ---------------------------------------------------------------------------

function FollowUpSection({
  brief,
  onAdd,
  onStatus,
  onResult,
  onRemove,
}: {
  brief: Brief;
  onAdd: (question: string, linked: string, dueStage: FollowUpStage) => void;
  onStatus: (id: string, status: FollowUpStatus) => void;
  onResult: (id: string, result: string) => void;
  onRemove: (id: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [linked, setLinked] = useState("");
  const [dueStage, setDueStage] = useState<FollowUpStage>("ONE_DAY");
  const overdue = useMemo(() => new Set(overdueFollowUps(brief).map((f) => f.follow_up_id)), [brief]);

  return (
    <SectionCard
      kicker="Follow-up"
      title="Follow-up plan"
      subtitle="Checks for live, 1d, 5d and 20d. Overdue unanswered checks are surfaced."
    >
      {brief.follow_up_checks.length === 0 ? (
        <Empty>No follow-up checks scheduled.</Empty>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {brief.follow_up_checks.map((f) => (
            <li key={f.follow_up_id} className="flex flex-col gap-1 rounded-md border border-border bg-background/40 px-2.5 py-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-num text-[10px] uppercase tracking-[0.06em] text-muted-foreground">due {f.due_stage}</span>
                <StateBadge variant={f.status === "ANSWERED" ? "neutral" : "pending"} label={f.status} />
                {overdue.has(f.follow_up_id) ? <StateBadge variant="warning" label="OVERDUE" /> : null}
                {f.linked_hypothesis ? <span className="font-num text-[10px] text-muted-foreground">→ {f.linked_hypothesis}</span> : null}
              </div>
              <p className="text-xs leading-relaxed text-foreground/90">{f.question}</p>
              <div className="flex flex-wrap items-end gap-2">
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground/80">Status</span>
                  <SelectInput value={f.status} onChange={(e) => onStatus(f.follow_up_id, e.target.value as FollowUpStatus)} aria-label={`Status for follow-up: ${f.question}`}>
                    {FOLLOW_UP_STATUSES.map((s) => (<option key={s} value={s}>{s}</option>))}
                  </SelectInput>
                </label>
                <label className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground/80">Result</span>
                  <TextInput value={f.result} onChange={(e) => onResult(f.follow_up_id, e.target.value)} placeholder="answer when resolved" />
                </label>
                <RemoveButton onClick={() => onRemove(f.follow_up_id)} label="Remove follow-up" />
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
        <div className="sm:col-span-2"><Field label="Question"><TextInput value={question} onChange={(e) => setQuestion(e.target.value)} /></Field></div>
        <Field label="Linked hypothesis">
          <SelectInput value={linked} onChange={(e) => setLinked(e.target.value)}>
            <option value="">(none)</option>
            {brief.mechanism_hypotheses.map((h) => (<option key={h.hypothesis_id} value={h.hypothesis_id}>{h.name || h.hypothesis_id}</option>))}
          </SelectInput>
        </Field>
        <Field label="Due stage">
          <SelectInput value={dueStage} onChange={(e) => setDueStage(e.target.value as FollowUpStage)}>
            {FOLLOW_UP_STAGES.map((s) => (<option key={s} value={s}>{s}</option>))}
          </SelectInput>
        </Field>
      </div>
      <div>
        <GhostButton
          disabled={!question.trim()}
          onClick={() => {
            onAdd(question, linked, dueStage);
            setQuestion(""); setLinked("");
          }}
        >
          + Add check
        </GhostButton>
      </div>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Revision log (append-only)
// ---------------------------------------------------------------------------

function RevisionLogSection({
  brief,
  onAppend,
}: {
  brief: Brief;
  onAppend: (what: string, why: string, linked: string) => void;
}) {
  const [what, setWhat] = useState("");
  const [why, setWhy] = useState("");
  const [linked, setLinked] = useState("");

  return (
    <SectionCard kicker="Revision log" title="Revision log" subtitle="Append-only. Earlier reasoning stays visible; the original thesis is never overwritten without a trace.">
      <ol className="flex flex-col gap-1.5">
        {brief.revision_log.map((r) => (
          <li key={r.id} className="rounded-md border border-border bg-background/40 px-2.5 py-1.5 text-xs">
            <div className="mb-0.5 flex flex-wrap items-center gap-2">
              <span className="font-num text-[10px] text-muted-foreground">{r.timestamp}</span>
              <StateBadge variant="neutral" label={r.stage} />
              {r.linked_fact_or_falsifier ? <span className="font-num text-[10px] text-muted-foreground">link: {r.linked_fact_or_falsifier}</span> : null}
            </div>
            <p className="text-foreground/90">{r.what_changed}</p>
            {r.why_it_changed ? <p className="text-[11px] text-muted-foreground">Why: {r.why_it_changed}</p> : null}
          </li>
        ))}
      </ol>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
        <div className="sm:col-span-2"><Field label="What changed"><TextInput value={what} onChange={(e) => setWhat(e.target.value)} /></Field></div>
        <Field label="Why it changed"><TextInput value={why} onChange={(e) => setWhy(e.target.value)} /></Field>
        <Field label="Linked fact / falsifier"><TextInput value={linked} onChange={(e) => setLinked(e.target.value)} /></Field>
      </div>
      <div>
        <GhostButton
          disabled={!what.trim()}
          onClick={() => {
            onAppend(what, why, linked);
            setWhat(""); setWhy(""); setLinked("");
          }}
        >
          + Append revision
        </GhostButton>
      </div>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Claim ceiling
// ---------------------------------------------------------------------------

function ClaimCeilingSection({ brief, onPatch }: { brief: Brief; onPatch: (patch: Partial<Brief>) => void }) {
  return (
    <SectionCard kicker="Claim boundary" title="Claim ceiling" subtitle="Optional operator ceiling — it can never widen past the fixed non-claim below.">
      <Field label="Operator claim ceiling">
        <TextArea value={brief.claim_ceiling} onChange={(e) => onPatch({ claim_ceiling: e.target.value })} placeholder="the most this brief is allowed to assert" />
      </Field>
      <div className="rounded-md border border-border/70 bg-secondary/40 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
        <span className="font-semibold text-foreground/80">Fixed non-claim: </span>
        {NON_CLAIM}
      </div>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Export / import
// ---------------------------------------------------------------------------

function ExportImportBar({
  brief,
  onImport,
  importError,
}: {
  brief: Brief;
  onImport: (text: string) => void;
  importError: string | null;
}) {
  const [showImport, setShowImport] = useState(false);
  const [text, setText] = useState("");
  return (
    <SectionCard kicker="Export & import" title="Local export / import" subtitle="Deterministic Markdown or JSON. Exports are downloaded, never tracked in the repository.">
      <div className="flex flex-wrap items-center gap-2">
        <GhostButton
          data-testid="export-md"
          onClick={() => downloadText(`live-brief-${brief.brief_id}.md`, exportBriefMarkdown(brief, nowIso()), "text/markdown")}
        >
          Export Markdown
        </GhostButton>
        <GhostButton
          data-testid="export-json"
          onClick={() => downloadText(`live-brief-${brief.brief_id}.json`, exportBriefJson(brief, nowIso()), "application/json")}
        >
          Export JSON
        </GhostButton>
        <GhostButton onClick={() => setShowImport((s) => !s)} aria-expanded={showImport} aria-controls="import-panel">
          Import JSON
        </GhostButton>
      </div>

      {showImport ? (
        <div id="import-panel" className="flex flex-col gap-2">
          <Field label="Paste a live-event-brief-v1 JSON export">
            <TextArea value={text} onChange={(e) => setText(e.target.value)} rows={4} data-testid="import-textarea" />
          </Field>
          <div className="flex items-center gap-2">
            <GhostButton
              data-testid="import-submit"
              disabled={!text.trim()}
              onClick={() => onImport(text)}
            >
              Import
            </GhostButton>
            {importError ? (
              <p role="alert" className="text-[11px] text-destructive" data-testid="import-error">
                Import refused (existing briefs preserved): {importError}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Editor
// ---------------------------------------------------------------------------

function BriefEditor({
  brief,
  update,
  onStage,
  onDelete,
  onImport,
  importError,
  initialHistoricalPanel,
}: {
  brief: Brief;
  update: (fn: (b: Brief) => Brief) => void;
  onStage: (s: Stage) => void;
  onDelete: () => void;
  onImport: (text: string) => void;
  importError: string | null;
  initialHistoricalPanel?: HistoricalPanel | null;
}) {
  const patch = (p: Partial<Brief>) => update((b) => patchBrief(b, p, nowIso()));

  return (
    <div className="flex flex-col gap-3">
      <EditorHeader brief={brief} onStage={onStage} onDelete={onDelete} />

      <IdentitySection
        brief={brief}
        onPatch={patch}
        onAddSource={(label, url, note) =>
          patch({ source_references: [...brief.source_references, { id: genId("src"), label, url, note }] })
        }
        onRemoveSource={(id) => patch({ source_references: removeItem(brief.source_references, (s) => s.id, id) })}
      />

      <WhatChangedSection brief={brief} onPatch={patch} />

      <TypedEntriesSection
        kicker="Facts & interpretations"
        title="Facts, interpretations & unknowns"
        subtitle="Each note is typed. Interpretations never read as facts; unknowns stay visible until resolved."
        section="facts"
        entries={brief.fact_summary}
        defaultType="FACT"
        onAdd={(type, text, sourceRef, sourceNote) =>
          update((b) => addTypedEntry(b, "fact_summary", { type, text, source_reference: sourceRef, source_note: sourceNote }, nowIso(), genId("entry")))
        }
        onRemove={(id) => patch({ fact_summary: removeItem(brief.fact_summary, (e) => e.id, id) })}
      />

      <TypedEntriesSection
        kicker="Known unknowns"
        title="Known unknowns"
        subtitle="Open questions that stay visible until explicitly resolved."
        section="unknowns"
        entries={brief.known_unknowns}
        defaultType="UNKNOWN"
        onAdd={(type, text, sourceRef, sourceNote) =>
          update((b) => addTypedEntry(b, "known_unknowns", { type, text, source_reference: sourceRef, source_note: sourceNote }, nowIso(), genId("unk")))
        }
        onRemove={(id) => patch({ known_unknowns: removeItem(brief.known_unknowns, (e) => e.id, id) })}
      />

      <HypothesesSection
        brief={brief}
        onAdd={(name, path) =>
          update((b) => {
            const r = addHypothesis(b, { name, mechanism_path: path }, nowIso(), genId("hyp"));
            return r.ok ? r.brief : b;
          })
        }
        onState={(id, state) => patch({ mechanism_hypotheses: patchItem(brief.mechanism_hypotheses, (h) => h.hypothesis_id, id, { current_state: state }) })}
        onRemove={(id) => patch({ mechanism_hypotheses: removeItem(brief.mechanism_hypotheses, (h) => h.hypothesis_id, id) })}
      />

      <AssetRolesSection
        brief={brief}
        onAdd={(asset, role, benchmark, lens, channel, window, basis, limitations) =>
          update((b) => addAssetRole(b, { asset, role, benchmark, sector_or_relative_lens: lens, expected_channel: channel, window, basis, limitations }, nowIso(), genId("asset")))
        }
        onRemove={(id) => patch({ asset_roles: removeItem(brief.asset_roles, (a) => a.id, id) })}
      />

      <ReactionsSection
        brief={brief}
        onAdd={(horizon, value, unit, basis, window, source) =>
          update((b) => addMarketReaction(b, { horizon, value, unit, basis, window, source }, nowIso(), genId("rx")))
        }
        onRemove={(id) => patch({ market_reactions: removeItem(brief.market_reactions, (m) => m.id, id) })}
      />

      <SectionCard kicker="Historical context" title="Historical research context" subtitle="Descriptive published Second Order evidence, loaded lazily — context only.">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label="Declared comparable cohort">
            <SelectInput
              value={brief.historical_context.comparable_cohort}
              onChange={(e) => patch({ historical_context: { ...brief.historical_context, comparable_cohort: e.target.value as ComparableCohort } })}
              data-testid="cohort-select"
            >
              {COMPARABLE_COHORTS.map((c) => (<option key={c} value={c}>{c}</option>))}
            </SelectInput>
          </Field>
          <div className="sm:col-span-2">
            <Field label="Context notes">
              <TextInput value={brief.historical_context.notes} onChange={(e) => patch({ historical_context: { ...brief.historical_context, notes: e.target.value } })} />
            </Field>
          </div>
        </div>
        <LiveBriefHistoricalContext cohort={brief.historical_context.comparable_cohort} initialOpenPanel={initialHistoricalPanel ?? null} />
      </SectionCard>

      <FalsifiersSection
        brief={brief}
        onAdd={(statement, linked, observable, window) =>
          update((b) => addFalsifier(b, { statement, linked_hypothesis: linked, observable, evaluation_window: window }, nowIso(), genId("fals")))
        }
        onStatus={(id, status) => patch({ falsifiers: patchItem(brief.falsifiers, (f) => f.falsifier_id, id, { status, as_of: nowIso() }) })}
        onRemove={(id) => patch({ falsifiers: removeItem(brief.falsifiers, (f) => f.falsifier_id, id) })}
      />

      <FollowUpSection
        brief={brief}
        onAdd={(question, linked, dueStage) =>
          update((b) => addFollowUp(b, { question, linked_hypothesis: linked, due_stage: dueStage }, nowIso(), genId("fu")))
        }
        onStatus={(id, status) => patch({ follow_up_checks: patchItem(brief.follow_up_checks, (f) => f.follow_up_id, id, { status, as_of: nowIso() }) })}
        onResult={(id, result) => patch({ follow_up_checks: patchItem(brief.follow_up_checks, (f) => f.follow_up_id, id, { result, as_of: nowIso() }) })}
        onRemove={(id) => patch({ follow_up_checks: removeItem(brief.follow_up_checks, (f) => f.follow_up_id, id) })}
      />

      <RevisionLogSection
        brief={brief}
        onAppend={(what, why, linked) =>
          update((b) => appendRevision(b, { what_changed: what, why_it_changed: why, linked_fact_or_falsifier: linked }, nowIso(), genId("rev")))
        }
      />

      <ClaimCeilingSection brief={brief} onPatch={patch} />

      <ExportImportBar brief={brief} onImport={onImport} importError={importError} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export interface LiveBriefPageProps {
  /** Static-render test seams (the live path loads from localStorage). */
  initialBriefs?: Brief[];
  initialActiveBriefId?: string | null;
  initialHistoricalPanel?: HistoricalPanel | null;
}

export function LiveBriefPage({
  initialBriefs,
  initialActiveBriefId = null,
  initialHistoricalPanel = null,
}: LiveBriefPageProps = {}) {
  const [briefs, setBriefs] = useState<Brief[]>(() => initialBriefs ?? loadBriefs());
  const [selectedId, setSelectedId] = useState<string | null>(() => initialActiveBriefId);
  const [importError, setImportError] = useState<string | null>(null);

  // Persist locally on change.  Effects never run during a static render, so
  // this touches localStorage only in the browser.
  useEffect(() => {
    saveBriefs(briefs);
  }, [briefs]);

  const activeId = selectedId && briefs.some((b) => b.brief_id === selectedId) ? selectedId : briefs[0]?.brief_id ?? null;
  const active = briefs.find((b) => b.brief_id === activeId) ?? null;

  const createNew = () => {
    const id = genId("brief");
    const brief = createBrief(
      { title: "Untitled live event", event_family: "", event_type: "", event_date: "", scheduled_timestamp: "", timezone: "" },
      nowIso(),
      id,
      genId("rev"),
    );
    setBriefs((bs) => [...bs, brief]);
    setSelectedId(id);
  };

  const updateActive = (fn: (b: Brief) => Brief) => {
    if (!active) return;
    const next = fn(active);
    setBriefs((bs) => upsertBrief(bs, next));
  };

  const changeStage = (s: Stage) => updateActive((b) => setStage(b, s, nowIso(), genId("rev")));

  const deleteActive = () => {
    if (!active) return;
    setBriefs((bs) => removeBrief(bs, active.brief_id));
    setSelectedId(null);
  };

  const importJson = (text: string) => {
    const r = importBriefJson(text);
    if (!r.ok) {
      setImportError(r.errors[0] ?? "invalid brief");
      return;
    }
    setImportError(null);
    setBriefs((bs) => upsertBrief(bs, r.brief));
    setSelectedId(r.brief.brief_id);
  };

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-4">
      <header className="flex flex-col gap-2">
        <p className="section-kicker">Second Order · live</p>
        <h1 className="font-headline text-xl font-semibold tracking-[-0.01em] text-foreground">Live Event Brief</h1>
        <p className="max-w-3xl text-xs leading-relaxed text-muted-foreground">
          Structure a live event into sourced facts, competing mechanisms, asset roles, timestamped
          market reactions, historical context, falsifiers and 1d/5d/20d follow-up — locally, with no
          provider call or backend write. Everything is saved in this browser only.
        </p>
        <NonClaimBanner />
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <div className="lg:sticky lg:top-16 lg:self-start">
          <BriefList briefs={briefs} activeId={activeId} onSelect={setSelectedId} onCreate={createNew} />
        </div>
        <div className="min-w-0">
          {active ? (
            <BriefEditor
              key={active.brief_id}
              brief={active}
              update={updateActive}
              onStage={changeStage}
              onDelete={deleteActive}
              onImport={importJson}
              importError={importError}
              initialHistoricalPanel={initialHistoricalPanel}
            />
          ) : (
            <EmptyEditor onCreate={createNew} />
          )}
        </div>
      </div>

      <footer>
        <NonClaimBanner />
      </footer>
    </div>
  );
}

export default LiveBriefPage;
