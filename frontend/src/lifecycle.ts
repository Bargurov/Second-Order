// The interface freeze: reads of the store, the baselines and the freezable drafts, and the four explicit actions
// (upgrade the store, import a kept package, preview a freeze, approve one freeze). The server decides everything;
// this module only shapes the requests, refuses replies it cannot read, and never repeats an action by itself.
import type { Loaded } from "./api";

export const LIFECYCLE_VERSION = "lifecycle-freeze-0.1";
export const LIFECYCLE_HEADER = "X-Second-Order-Lifecycle";
export const FROZEN_NOT_EVALUATED = "Frozen · Not evaluated";
export const H15_OBSERVABLES = ["yield:ust2y_cmt_h15", "yield:ust10y_cmt_h15"] as const;
export type H15Observable = (typeof H15_OBSERVABLES)[number];
export const OBSERVABLE_LABEL: Record<string, string> = {
  "yield:ust2y_cmt_h15": "2-year Treasury yield (Board H.15)",
  "yield:ust10y_cmt_h15": "10-year Treasury yield (Board H.15)",
  "yield:ust2y_cmt": "2-year Treasury yield (FRED DGS2)",
  "yield:ust10y_cmt": "10-year Treasury yield (FRED DGS10)",
};
/** YYYY-MM-DDTHH:MM:SS±HH:MM: the publication time with its offset, as the source states it. */
export const EXPLICIT_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/;

export interface StoreState {
  exists: boolean; schema: number | null; interface_freezes: boolean; assessments?: boolean; detail: string | null;
}

export interface HypothesisRow {
  hypothesis_id: string; headline: string; published_at: string; frozen_at: string; recorded_at: string;
  evidence_class: string; usage: string; engine_provider: string; baseline_snapshot_id: string | null;
  origin: "manual" | "model" | "outside_interface"; evaluations: number; status: string;
}
export interface Overview {
  lifecycle_version: string; store: StoreState; hypotheses: HypothesisRow[]; classification: string;
}

export interface Coverage {
  observable_id?: string; first_date?: string; last_date?: string; classified_from?: string;
  classified_through?: string; rows?: number; statuses?: Record<string, number>;
}
export interface BaselineSummary {
  snapshot_id: string; provider: string; provider_label: string; retrieved_at: string; possession_note: string;
  vintage_date: string | null; vintage_note: string | null; created_at: string | null;
  package: { package_id: string; package_sha256: string; received_at: string; url: string } | null;
  source_prepared_as_stated: string | null; adapter_version: string; coverage: Record<string, Coverage>;
}
export interface PackageRow {
  package_id: string; status: string; detail: string | null; received_at: string; requested_at: string;
  sha256: string; bytes: number; coverage: { first: string; last: string } | null; release_prepared: string | null;
  validated_at: string | null; importable: boolean; snapshots: string[];
}
export interface Baselines {
  lifecycle_version: string; snapshots: BaselineSummary[]; packages: PackageRow[];
  problems: { retrieval: string; problem: string }[]; note: string;
}

export interface DraftRow {
  draft_id: string; capture_id: string; headline: string; published_at: string; published_at_as_supplied: string;
  mode: string; outcome: string; prompt_version: string; model: string;
  review: { state: string; status?: string | null; latest_saved_at?: string }; eligible: boolean; reasons: string[];
}
export interface Drafts {
  lifecycle_version: string; contract: string; drafts: DraftRow[];
  unreadable: { capture_id: string | null; draft_id: string | null; problem: string }[]; note: string;
}

export interface LegContent {
  id: string; node_id: string; primary: boolean; channel: string; observable_id: string; link: string;
  expected: string; horizon: number; falsifier: string; rationale: string; headline_reports_move: boolean;
}
export interface EffectiveHypothesis {
  event: { headline: string; source_url: string; published_at: string };
  evidence_class: string; usage: string; story_id: string;
  engine: { provider: string; model: string; prompt_hash: string; schema_version: string };
  summary: string; nodes: { id: string; label: string; kind: string }[];
  edges: { source: string; target: string }[]; legs: LegContent[];
}
export interface Origin {
  kind: "manual" | "model" | "outside_interface"; note?: string;
  manual_input?: Record<string, unknown>; manual_input_sha256?: string;
  draft_id?: string; capture_id?: string; draft_view_sha256?: string; prompt_version?: string;
  request_sha256?: string; response_sha256?: string | null; request_id?: string | null; model?: string;
  model_output_sha256?: string;
  review?: { review_id: string; sequence: number; status: string; saved_at: string; attributed_to: string };
  corrections?: { summary: string | null; legs: Record<string, Record<string, unknown>> };
  published_at_as_supplied?: string; publication_precision?: string;
}
export interface Freshness {
  policy: string; covered?: false; problem?: string; published_date?: string; required_session?: string;
  series?: Record<string, { observable_id: string; classified_from: string; classified_through: string;
    required_session_status: string }>;
}
export interface Readiness {
  rules_version: string; rules_hash: string;
  legs: Record<string, { observable_id: string; horizon: number; event_anchor: string | null; history_sessions: number;
    reference_windows: number; required_reference_windows: number | null; scorable: boolean }>;
}
export interface Scoring {
  freeze_date_new_york: string; rule: string; expected_score_anchor: string | null;
  legs: Record<string, { horizon: number; expected_target: string | null }>; note: string;
}
export interface Binding {
  lifecycle_version: string; freeze_policy: string; effective_hypothesis: EffectiveHypothesis; origin: Origin;
  baseline_snapshot_id: string; source_bindings: Record<string, string>; freeze_date_new_york: string;
}
export interface Preview {
  lifecycle_version: string; preview_sha256: string; binding: Binding; effective_sha256: string;
  freezable: boolean; blockers: string[]; previewed_at: string; baseline: BaselineSummary;
  freshness: Freshness | null; readiness: Readiness | null; policy_note: string; scoring: Scoring;
  measurement_convention: string; classification: string; limitations: string[]; freeze_time: string;
  provider_called: false; written: false;
}
export interface FrozenView {
  lifecycle_version: string; hypothesis_id: string; hypothesis: EffectiveHypothesis & { frozen_at: string };
  recorded_at: string; frozen_at: string; bound_at: string | null; baseline: BaselineSummary | null; status: string;
  evaluations: number; origin: Origin; effective_sha256: string | null; action_id: string | null;
  freshness: Freshness | null; scoring: Scoring; measurement_convention: string; classification: string | null;
  limitations: string[];
}
export interface ActionState {
  lifecycle_version: string; action_id: string; state: "frozen" | "not_recorded"; hypothesis_id?: string;
  recorded_at?: string; status?: string; detail: string;
}
export interface Frozen {
  lifecycle_version: string; action_id: string; state: "frozen"; created: boolean; hypothesis_id: string;
  recorded_at: string; status: string;
}

export interface Inputs {
  origin: "manual" | "model"; manual: ManualPayload | null; draft_id: string | null; baseline_snapshot_id: string;
}

// ---------------------------------------------------------------- reading

const SHA = /^[0-9a-f]{64}$/;
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

function detail(body: unknown): string | null {
  return typeof body === "object" && body !== null && typeof (body as { detail?: unknown }).detail === "string"
    ? (body as { detail: string }).detail : null;
}

/** A lifecycle reply is accepted only with this client's version and the fields its pages read. */
export function readable(body: unknown, check: (value: Record<string, unknown>) => boolean): boolean {
  if (typeof body !== "object" || body === null) return false;
  const value = body as Record<string, unknown>;
  return value.lifecycle_version === LIFECYCLE_VERSION && check(value);
}

export const isOverview = (value: Record<string, unknown>) =>
  Array.isArray(value.hypotheses) && typeof value.store === "object" && value.store !== null &&
  (value.hypotheses as HypothesisRow[]).every((row) => SHA.test(row.hypothesis_id) && typeof row.status === "string");
export const isBaselines = (value: Record<string, unknown>) =>
  Array.isArray(value.snapshots) && Array.isArray(value.packages) &&
  (value.snapshots as BaselineSummary[]).every((row) => SHA.test(row.snapshot_id) && typeof row.coverage === "object");
export const isDrafts = (value: Record<string, unknown>) =>
  Array.isArray(value.drafts) && (value.drafts as DraftRow[]).every((row) => SHA.test(row.draft_id) &&
    typeof row.eligible === "boolean" && Array.isArray(row.reasons) && (row.eligible === (row.reasons.length === 0)));
export const isFrozenView = (value: Record<string, unknown>) =>
  typeof value.hypothesis_id === "string" && SHA.test(value.hypothesis_id) && typeof value.hypothesis === "object" &&
  value.hypothesis !== null && typeof value.status === "string" && typeof value.frozen_at === "string";
/** A preview must bind what it shows: the effective hypothesis inside the binding, and a 64-hex SHA-256. */
export const isPreview = (value: Record<string, unknown>) => {
  const binding = value.binding as Binding | undefined;
  return typeof value.preview_sha256 === "string" && SHA.test(value.preview_sha256) && typeof binding === "object" &&
    binding !== null && typeof binding.effective_hypothesis === "object" && typeof value.freezable === "boolean" &&
    Array.isArray(value.blockers) && value.freezable === ((value.blockers as unknown[]).length === 0) &&
    value.provider_called === false && value.written === false &&
    binding.baseline_snapshot_id === (value.baseline as BaselineSummary | undefined)?.snapshot_id;
};

export async function getLifecycle<T>(path: string, signal: AbortSignal,
                                      check: (value: Record<string, unknown>) => boolean): Promise<Loaded<T>> {
  let response: Response;
  try {
    response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch {
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (response.status === 404) return { state: "missing", message: detail(body) ?? "Not found." };
  if (!response.ok) return { state: "error", message: detail(body) ?? `Unexpected response (${response.status}).` };
  if (!readable(body, check)) return { state: "error", message: "The reply could not be read by this page." };
  return { state: "ready", data: body as T };
}

export const fetchOverview = (signal: AbortSignal) => getLifecycle<Overview>("/api/lifecycle", signal, isOverview);
export const fetchBaselines = (signal: AbortSignal) =>
  getLifecycle<Baselines>("/api/lifecycle/baselines", signal, isBaselines);
export const fetchFreezableDrafts = (signal: AbortSignal) =>
  getLifecycle<Drafts>("/api/lifecycle/drafts", signal, isDrafts);
export const fetchFrozen = (id: string, signal: AbortSignal) =>
  getLifecycle<FrozenView>(`/api/lifecycle/hypotheses/${encodeURIComponent(id)}`, signal, isFrozenView);

// ---------------------------------------------------------------- the explicit actions

export type ActionResult<T> =
  | { state: "done"; status: number; data: T }
  | { state: "refused"; status: number; message: string; preview: Preview | null }
  | { state: "unconfirmed"; message: string };

/** One POST from this page. A missing reply or a server error is "unconfirmed": nothing is sent again by itself. */
export async function lifecycleAction<T>(path: string, body: object,
                                         check: (value: Record<string, unknown>) => boolean): Promise<ActionResult<T>> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST", body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", Accept: "application/json", [LIFECYCLE_HEADER]: "1" },
    });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server. Nothing was sent again; check the outcome." };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (response.status >= 500) {
    return { state: "unconfirmed", message: detail(payload) ?? `The server failed (${response.status}); check the outcome.` };
  }
  if (!response.ok) {
    const preview = typeof payload === "object" && payload !== null && "preview" in payload &&
      readable((payload as { preview: unknown }).preview, isPreview) ? (payload as { preview: Preview }).preview : null;
    return { state: "refused", status: response.status, message: detail(payload) ?? `Refused (${response.status}).`,
             preview };
  }
  if (!readable(payload, check)) return { state: "unconfirmed", message: "The server replied, but the reply could not be read." };
  return { state: "done", status: response.status, data: payload as T };
}

export const importBaseline = (packageId: string, start: string) =>
  lifecycleAction<{ lifecycle_version: string; created: boolean; snapshot: BaselineSummary }>(
    "/api/lifecycle/baselines", { package_id: packageId, start },
    (value) => typeof value.created === "boolean" && typeof value.snapshot === "object");
/** The explicit upgrade to schema 4: it only adds tables (freeze and assessment actions); every record stays. */
export const upgradeStore = () =>
  lifecycleAction<{ lifecycle_version: string; migrated: boolean; schema_version: number }>(
    "/api/lifecycle/store-upgrade", { upgrade_to: 4 }, (value) => value.schema_version === 4);
export const previewFreeze = (inputs: Inputs) =>
  lifecycleAction<Preview>("/api/lifecycle/preview", { inputs }, isPreview);
/** The approval names the preview it approves; the server stamps the time and recomputes the preview first. */
export const approveFreeze = (inputs: Inputs, preview: Preview) =>
  lifecycleAction<Frozen>("/api/lifecycle/freezes",
    { inputs, preview_sha256: preview.preview_sha256, approve_freeze: true, previewed_binding: preview.binding },
    (value) => value.state === "frozen" && typeof value.hypothesis_id === "string" && SHA.test(value.hypothesis_id));
/** After a lost reply: read whether this approval froze anything. A read; it never approves again. */
export const checkAction = (actionId: string, signal: AbortSignal) =>
  getLifecycle<ActionState>(`/api/lifecycle/actions/${encodeURIComponent(actionId)}`, signal,
    (value) => value.state === "frozen" || value.state === "not_recorded");

// ---------------------------------------------------------------- the manual form

export interface ManualLeg {
  observable_id: H15Observable; expected: "" | "up" | "down"; horizon: "" | "1" | "5" | "20";
  link: "" | "direct" | "proxy"; channel: string; rationale: string; falsifier: string;
  headline_reports_move: "" | "yes" | "no";
}
export interface ManualForm {
  headline: string; source_url: string; published_at: string; story_id: string; summary: string; authoring: string;
  primary: "" | H15Observable; legs: ManualLeg[];
}
export interface ManualPayload {
  headline: string; source_url: string; published_at: string; story_id: string; summary: string; authoring: string;
  legs: { observable_id: string; primary: boolean; expected: string; horizon: number; link: string; channel: string;
    rationale: string; falsifier: string; headline_reports_move: boolean }[];
}

/** An empty form: nothing is preselected, so every choice (direction, horizon, link, flag, primary) is the user's. */
export function emptyManual(): ManualForm {
  return {
    headline: "", source_url: "", published_at: "", story_id: "", summary: "", authoring: "", primary: "",
    legs: H15_OBSERVABLES.map((observable_id) => ({ observable_id, expected: "", horizon: "", link: "", channel: "",
      rationale: "", falsifier: "", headline_reports_move: "" })),
  };
}

/** The form as the server's strict input, or what is still missing. The server checks everything again. */
export function manualPayload(form: ManualForm): { payload: ManualPayload | null; missing: string[] } {
  const missing: string[] = [];
  const text = (value: string, label: string) => { if (!value.trim()) missing.push(label); return value.trim(); };
  text(form.headline, "headline");
  text(form.source_url, "source URL");
  if (!EXPLICIT_TIME.test(form.published_at.trim())) missing.push("publication time with its UTC offset");
  text(form.story_id, "story ID");
  text(form.summary, "summary");
  text(form.authoring, "how it was authored");
  if (!form.primary) missing.push("the primary leg");
  for (const leg of form.legs) {
    const name = OBSERVABLE_LABEL[leg.observable_id];
    if (!leg.expected) missing.push(`${name}: direction`);
    if (!leg.horizon) missing.push(`${name}: horizon`);
    if (!leg.link) missing.push(`${name}: link`);
    if (!leg.headline_reports_move) missing.push(`${name}: whether the headline reports the move`);
    for (const [value, label] of [[leg.channel, "channel"], [leg.rationale, "rationale"], [leg.falsifier, "falsifier"]]) {
      if (!value.trim()) missing.push(`${name}: ${label}`);
    }
  }
  if (missing.length) return { payload: null, missing };
  return {
    missing,
    payload: {
      headline: form.headline.trim(), source_url: form.source_url.trim(), published_at: form.published_at.trim(),
      story_id: form.story_id.trim(), summary: form.summary.trim(), authoring: form.authoring.trim(),
      legs: form.legs.map((leg) => ({
        observable_id: leg.observable_id, primary: form.primary === leg.observable_id, expected: leg.expected,
        horizon: Number(leg.horizon), link: leg.link, channel: leg.channel.trim(), rationale: leg.rationale.trim(),
        falsifier: leg.falsifier.trim(), headline_reports_move: leg.headline_reports_move === "yes",
      })),
    },
  };
}

export function hypothesisHref(id: string): string {
  return `/hypotheses/${encodeURIComponent(id)}`;
}

/** "board-h15" etc. as a reader-facing name. */
export function providerName(provider: string): string {
  return provider === "board-h15" ? "Federal Reserve Board H.15 release package" : provider === "fred" ? "FRED" : provider;
}

export const ORIGIN_LABEL: Record<Origin["kind"], string> = {
  manual: "Manual hypothesis (interface form)", model: "Reviewed model draft",
  outside_interface: "Frozen outside this interface",
};
