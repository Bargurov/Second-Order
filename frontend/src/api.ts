import { useEffect, useState } from "react";
import type {
  DraftIndex, DraftReviewView, LoadedDraft, ReviewHistory, ReviewPayload, ReviewRecord,
} from "./draftTypes";
import { readAnalyses, type AnalysesLibrary } from "./analyses.ts";
import type { AttemptState, IntakePayload, MockOutcome } from "./intake";
import { LIBRARY_VIEW_VERSION, type CaseLibraryIndex, type LibraryCaseView } from "./library.ts";
import { MARKET_CONTEXT_VIEW_VERSION, type MarketContextView } from "./marketContext.ts";
import type { Dossier, DossierIndex } from "./types";

export const VIEW_VERSION = "dossier-view-0.3";
export const DRAFT_VIEW_VERSION = "draft-review-view-0.1";
export const REVIEW_HISTORY_VERSION = "draft-review-history-0.2";
export const REVIEW_RECORD_VERSION = "draft-human-review-0.1";
export const INTAKE_FLOW_VERSION = "event-draft-flow-0.1";
export const VIEW_HASH_HEADER = "X-Draft-View-SHA256";

export type Loaded<T> =
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "missing"; message: string }
  | { state: "not-prepared"; message: string }
  | { state: "error"; message: string };

const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

function detail(body: unknown): string | null {
  return typeof body === "object" && body !== null && typeof (body as { detail?: unknown }).detail === "string"
    ? (body as { detail: string }).detail
    : null;
}

export interface IntakePreview {
  flow_version: string;
  status: string;
  capture_id: string;
  model: string;
  effort: string;
  max_tokens: number;
  prompt_version: string;
  request_sha256: string;
  request_bytes: number;
  request: Record<string, unknown>;
  /** published_at is the normalized UTC instant; published_at_as_supplied is exactly what the operator gave. */
  times: { published_at: string; published_at_as_supplied: string; captured_at: string };
  current_code: { comparison: string; detail: string };
  /** Whether this action contacted the provider: a capture or preview never does. */
  provider_called: false;
  cost_estimate: {
    mock_run_usd: number;
    estimated_real_run_if_output_reaches_max_usd: number;
    input_tokens_assumed: number;
    output_tokens_at_max: number;
    prices: { input_usd_per_mtok: number; output_usd_per_mtok: number; read_on: string; source: string };
    assumptions: string[];
    caveat: string;
  };
  /** What this server offers. Paid sending is enabled only by an explicit server option, and an enabled mode is
   *  not an approval: each send still needs its own explicit approval of this request's SHA-256. */
  modes: { mock: { enabled: boolean; detail: string }; paid: { enabled: boolean; detail: string } };
  /** Present only on a capture that named the Inbox entry version its form started from. */
  origin?: { recorded: boolean; problem: string | null; link: unknown };
}

/** What a mock dispatch, a paid send or a recovery established. */
export interface MockDraftResult {
  flow_version: string;
  status: "prepared_for_human_review";
  capture_id: string;
  draft_id: string;
  outcome: "draft" | "no_draft" | "invalid" | "technical_failure";
  recorded_outcome: string;
  mode: "mock" | "paid";
  recovered: boolean;
  /** Whether this action contacted the provider. */
  provider_called: boolean;
  /** From the response's usage at published rates; null when no usage was returned. */
  cost_usd: number | null;
  attempts: 1;
  retries: 0;
  frozen: false;
  evaluated: false;
}

type LocalAction<T> = { state: "saved"; preview: T } | { state: "failed" | "unconfirmed"; message: string };

async function localAction<T>(path: string, body: object): Promise<LocalAction<T>> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Second-Order-Intake": "1" },
      body: JSON.stringify(body),
    });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server. Nothing was retried; the local record may still have been written." };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    // A 4xx is a refusal made before anything was written; a 5xx does not prove what was recorded.
    const message = detail(payload) ?? `Unexpected response (${response.status}).`;
    return { state: response.status >= 500 ? "unconfirmed" : "failed", message };
  }
  if ((payload as { flow_version?: unknown } | null)?.flow_version !== INTAKE_FLOW_VERSION) {
    return { state: "unconfirmed", message: "The server replied, but its event-flow result could not be verified." };
  }
  return { state: "saved", preview: payload as T };
}

export const captureEvent = (body: IntakePayload) => localAction<IntakePreview>("/api/intake", body);

export type DispatchResult =
  | { state: "saved"; result: MockDraftResult }
  | { state: "failed" | "unconfirmed"; message: string };

export async function dispatchMock(captureId: string, requestHash: string,
                                   mockOutcome: MockOutcome): Promise<DispatchResult> {
  const result = await localAction<MockDraftResult>(
    `/api/intake/${encodeURIComponent(captureId)}/mock-drafts`,
    { request_sha256: requestHash, mock_outcome: mockOutcome },
  );
  return result.state === "saved" ? { state: "saved", result: result.preview } : result;
}

/**
 * The one paid action: send the approved saved request once. The body repeats the request hash and the planning
 * estimate the preview showed, and says the paid request is approved; the server checks all three first.
 */
export async function dispatchPaid(captureId: string, requestHash: string, estimate: number): Promise<DispatchResult> {
  const result = await localAction<MockDraftResult>(
    `/api/intake/${encodeURIComponent(captureId)}/paid-drafts`,
    { request_sha256: requestHash, approve_paid_request: true, estimated_max_usd: estimate },
  );
  return result.state === "saved" ? { state: "saved", result: result.preview } : result;
}

/** Publish an already recorded response for review. Nothing is sent or generated again. */
export async function publishRecorded(captureId: string, requestHash: string): Promise<DispatchResult> {
  const result = await localAction<MockDraftResult>(
    `/api/intake/${encodeURIComponent(captureId)}/publish`, { request_sha256: requestHash },
  );
  return result.state === "saved" ? { state: "saved", result: result.preview } : result;
}

/** What has been recorded for a capture. A read: safe to repeat, and it never sends or writes anything. */
export async function fetchAttemptState(captureId: string): Promise<
  { state: "ready"; data: AttemptState } | { state: "error"; message: string }
> {
  let response: Response;
  try {
    response = await fetch(`/api/intake/${encodeURIComponent(captureId)}/attempt`,
                           { headers: { Accept: "application/json" } });
  } catch {
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) return { state: "error", message: detail(body) ?? `Unexpected response (${response.status}).` };
  if ((body as { flow_version?: unknown } | null)?.flow_version !== INTAKE_FLOW_VERSION) {
    return { state: "error", message: "The server's attempt state could not be verified." };
  }
  return { state: "ready", data: body as AttemptState };
}

/** One saved capture as GET /api/intake lists it: verified (with its labels) or refused with the reason. */
export interface SavedCapture {
  capture_id: string;
  state: string;
  problem?: string;
  headline?: string;
  published_at?: string;
  captured_at?: string;
  request_sha256?: string;
}

/** A read-only GET: parse a JSON reply from this event flow, or say why it could not be read. */
async function readIntake(path: string): Promise<{ state: "ready"; body: Record<string, unknown> } |
                                                 { state: "error"; message: string }> {
  let response: Response;
  try {
    response = await fetch(path, { headers: { Accept: "application/json" } });
  } catch {
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) return { state: "error", message: detail(body) ?? `Unexpected response (${response.status}).` };
  if ((body as { flow_version?: unknown } | null)?.flow_version !== INTAKE_FLOW_VERSION) {
    return { state: "error", message: "The server's reply could not be verified as this event flow's." };
  }
  return { state: "ready", body: body as Record<string, unknown> };
}

/** The saved captures, oldest first. A read: nothing is captured, sent or written. */
export async function fetchCaptures(): Promise<{ state: "ready"; data: SavedCapture[] } |
                                               { state: "error"; message: string }> {
  const read = await readIntake("/api/intake");
  if (read.state !== "ready") return read;
  if (!Array.isArray(read.body.captures)) return { state: "error", message: "The saved events could not be read." };
  return { state: "ready", data: read.body.captures as SavedCapture[] };
}

export type Reopened =
  | { state: "ready"; preview: IntakePreview; attempt: AttemptState | "unreadable"; problem: string | null }
  | { state: "error"; message: string };

/**
 * Open a saved capture again, or refresh the one shown, with reads only: the server's verified saved request and
 * its current sending modes, then what the capture's attempt recorded. Nothing is captured, rebuilt, sent or
 * approved. A refresh names the hash it showed, and a different saved request is refused rather than shown. An
 * attempt state that cannot be read or verified is "unreadable", never "no attempt".
 */
export async function reopenCapture(captureId: string, shownHash?: string): Promise<Reopened> {
  const read = await readIntake(`/api/intake/${encodeURIComponent(captureId)}`);
  if (read.state !== "ready") return read;
  const preview = read.body as unknown as IntakePreview;
  const modes = preview.modes as Partial<IntakePreview["modes"]> | undefined;
  if (preview.capture_id !== captureId || preview.provider_called !== false ||
      !/^[a-f0-9]{64}$/.test(String(preview.request_sha256)) || typeof modes?.mock?.enabled !== "boolean" ||
      typeof modes?.paid?.enabled !== "boolean") {
    return { state: "error", message: "The saved preview could not be verified, so it is not shown." };
  }
  if (shownHash !== undefined && preview.request_sha256 !== shownHash) {
    return { state: "error", message: "The saved request's SHA-256 changed since this page showed it." };
  }
  const attempt = await fetchAttemptState(captureId);
  if (attempt.state !== "ready" || attempt.data.capture_id !== captureId) {
    const problem = attempt.state === "ready" ? "The attempt state named another capture." : attempt.message;
    return { state: "ready", preview, attempt: "unreadable", problem };
  }
  return { state: "ready", preview, attempt: attempt.data, problem: null };
}

/** A GET of one view, with the response headers when it succeeded. */
async function getView<T extends { view_version: string }>(
  path: string,
  signal: AbortSignal,
  expected: string,
): Promise<[Loaded<T>, Headers | null]> {
  let response: Response;
  try {
    response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return [{ state: "error", message: UNREACHABLE }, null];
  }
  const body: unknown = await response.json().catch(() => null);
  if (response.status === 404) return [{ state: "missing", message: detail(body) ?? "Not found" }, null];
  if (response.status === 503) return [{ state: "not-prepared", message: detail(body) ?? "Not prepared" }, null];
  if (!response.ok || body === null || typeof body !== "object") {
    const message = response.status >= 500 ? UNREACHABLE : `Unexpected response (${response.status}).`;
    return [{ state: "error", message }, null];
  }
  const version = (body as { view_version?: unknown }).view_version;
  if (version !== expected) {
    return [{ state: "error", message: `This client reads ${expected}; the server sent ${String(version)}.` }, null];
  }
  return [{ state: "ready", data: body as T }, response.headers];
}

async function getJson<T extends { view_version: string }>(path: string, signal: AbortSignal, expected = VIEW_VERSION) {
  return (await getView<T>(path, signal, expected))[0];
}

export const fetchIndex = (signal: AbortSignal) => getJson<DossierIndex>("/api/dossiers", signal);
export const fetchDossier = (id: string, signal: AbortSignal) =>
  getJson<Dossier>(`/api/dossiers/${encodeURIComponent(id)}`, signal);
export const fetchDrafts = (signal: AbortSignal) => getJson<DraftIndex>("/api/drafts", signal, DRAFT_VIEW_VERSION);
/** The committed case library: editorial content, read-only, independent of prepared files and runtime records. */
export const fetchLibrary = (signal: AbortSignal) =>
  getJson<CaseLibraryIndex>("/api/case-library", signal, LIBRARY_VIEW_VERSION);
export const fetchLibraryCase = (id: string, signal: AbortSignal) =>
  getJson<LibraryCaseView>(`/api/case-library/${encodeURIComponent(id)}`, signal, LIBRARY_VIEW_VERSION);

/**
 * A case's verified market context. Unlike the other reads, a refusal keeps the server's own explanation (a hash
 * mismatch, a bundle not yet prepared), because the page shows it in place of the context.
 */
export async function fetchMarketContext(id: string, signal: AbortSignal): Promise<Loaded<MarketContextView>> {
  let response: Response;
  try {
    response = await fetch(`/api/case-library/${encodeURIComponent(id)}/market-context`,
                           { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  const message = detail(body) ?? `Unexpected response (${response.status}).`;
  if (response.status === 404) return { state: "missing", message };
  if (response.status === 503) return { state: "not-prepared", message };
  if (!response.ok) return { state: "error", message };
  if ((body as { view_version?: unknown } | null)?.view_version !== MARKET_CONTEXT_VIEW_VERSION) {
    return { state: "error", message: "The market context could not be verified as this client's version." };
  }
  return { state: "ready", data: body as MarketContextView };
}

/** A prepared view with the fingerprint of the exact bytes served, which a review save must name. */
export async function fetchDraft(id: string, signal: AbortSignal): Promise<Loaded<LoadedDraft>> {
  const [loaded, headers] = await getView<DraftReviewView>(`/api/drafts/${encodeURIComponent(id)}`, signal,
                                                           DRAFT_VIEW_VERSION);
  if (loaded.state !== "ready") return loaded;
  const fingerprint = headers?.get(VIEW_HASH_HEADER) ?? "";
  if (!/^[a-f0-9]{64}$/.test(fingerprint)) {
    const message = "The server sent the draft without its fingerprint, so a review could not be bound to it.";
    return { state: "error", message };
  }
  return { state: "ready", data: { view: loaded.data, fingerprint } };
}

export const fetchReviews = (id: string, signal: AbortSignal) =>
  getJson<ReviewHistory>(`/api/drafts/${encodeURIComponent(id)}/reviews`, signal, REVIEW_HISTORY_VERSION);

/**
 * My analyses: the Tracker's analyses with a published review view, and their review state. A read: nothing is
 * written, sent or fetched. An entry this client cannot read is listed as unreadable rather than dropped.
 */
export async function fetchAnalyses(signal: AbortSignal): Promise<Loaded<AnalysesLibrary>> {
  let response: Response;
  try {
    response = await fetch("/api/analyses", { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) return { state: "error", message: detail(body) ?? `Unexpected response (${response.status}).` };
  const read = readAnalyses(body);
  return "library" in read ? { state: "ready", data: read.library } : { state: "error", message: read.problem };
}

/**
 * "conflict", "invalid" and "refused" are answers given before anything was written. "unconfirmed" means no
 * readable answer arrived: the version may or may not have been saved, and only the saved versions can tell.
 */
export type SaveResult =
  | { state: "saved"; record: ReviewRecord }
  | { state: "conflict" | "invalid" | "refused" | "unconfirmed"; message: string };

/**
 * Append one review version. The JSON body and the custom header make a cross-site page unable
 * to send it without a CORS preflight, which the server never grants. Nothing is retried automatically.
 */
export async function saveReview(id: string, payload: ReviewPayload): Promise<SaveResult> {
  let response: Response;
  try {
    response = await fetch(`/api/drafts/${encodeURIComponent(id)}/reviews`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Second-Order-Review": "1" },
      body: JSON.stringify(payload),
    });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server." };
  }
  const body: unknown = await response.json().catch(() => null);
  if (response.status === 201) {
    return (body as { record_version?: unknown } | null)?.record_version === REVIEW_RECORD_VERSION
      ? { state: "saved", record: body as ReviewRecord }
      : { state: "unconfirmed", message: "The server reported a new version, but its reply could not be read." };
  }
  const message = detail(body) ?? `Unexpected response (${response.status})`;
  if (response.status === 409) return { state: "conflict", message };
  if ([400, 404, 413, 415, 422].includes(response.status)) return { state: "invalid", message };
  if (response.status === 403) return { state: "refused", message };
  return { state: "unconfirmed", message: `The server answered with an error: ${message}.` };
}

/** Load once per key; GET-only, so retrying is always safe. */
export function useLoad<T>(load: (signal: AbortSignal) => Promise<Loaded<T>>, key: string): [Loaded<T>, () => void] {
  const [state, setState] = useState<Loaded<T>>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ state: "loading" });
    // A reply for a superseded key or attempt is dropped, even when it arrives after the newer one started.
    load(controller.signal).then((loaded) => { if (!controller.signal.aborted) setState(loaded); }, () => undefined);
    return () => controller.abort();
  }, [key, attempt]); // `load` is keyed by `key`; a new key is a new request.
  return [state, () => setAttempt((value) => value + 1)];
}
