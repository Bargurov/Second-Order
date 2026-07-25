/**
 * analysis-launch.ts — pure decision layer between opening an event and
 * paying for one.
 *
 * Two things stayed conflated before A1-1: navigating to the analysis surface
 * and calling a paid provider.  For an inbox candidate they are now separate
 * steps — the launch object only carries identity, and a second explicit
 * action decides what (if anything) the browser sends.
 *
 * Every identity is carried verbatim from the validated inbox payload; nothing
 * here re-derives a candidate handle, and the `aei-*` handle is never written
 * into the numeric saved-analysis field.
 */

import type { AnalysisLinkState, InboxEvent } from "./event-inbox";
import type { AnalyzeRequest } from "./api";

/** The three fields that together address one strict inbox candidate. */
export interface CandidateIdentity {
  candidate_id: string;
  parent_cluster_id: number;
  title_key: string;
}

export interface CandidateLink {
  status: AnalysisLinkState;
  /** Numeric `events.id` — present only for a candidate linked to exactly one
   *  saved analysis.  A conflict deliberately selects none. */
  analysisEventId: number | null;
}

/** A candidate opened from the Event Inbox: identity known, nothing run yet. */
export interface InboxLaunch {
  origin: "inbox";
  headline: string;
  context: string;
  candidate: CandidateIdentity;
  link: CandidateLink;
}

/**
 * A headline opened from anywhere else (Market Overview, Portfolio, Archive
 * re-run).  Those surfaces have no candidate identity, and the operator's
 * click there already IS the decision to analyze.
 */
export interface HeadlineLaunch {
  origin: "direct";
  headline: string;
  context?: string;
  eventId?: number;
}

export type AnalysisLaunch = InboxLaunch | HeadlineLaunch;

/**
 * What the operator may do with a launch:
 *   `run_paid`         — no saved analysis exists; a run calls a paid provider
 *                        and needs explicit confirmation;
 *   `open_saved`       — one saved analysis is linked; re-reading it is free;
 *   `blocked_conflict` — the registry links this candidate to more than one
 *                        analysis.  Nothing is offered: choosing one id for
 *                        the operator would silently open the wrong event.
 */
export type AnalysisAction = "run_paid" | "open_saved" | "blocked_conflict";

export function launchFromInboxEvent(ev: InboxEvent): InboxLaunch {
  const t = ev.analysis_target;
  return {
    origin: "inbox",
    headline: t.headline,
    context: t.context,
    candidate: {
      candidate_id: t.candidate_id,
      parent_cluster_id: t.parent_cluster_id,
      title_key: t.title_key,
    },
    link: {
      status: t.analysis_link_status,
      analysisEventId: t.analysis_event_id,
    },
  };
}

export function launchFromHeadline(
  headline: string,
  opts?: { context?: string; eventId?: number },
): HeadlineLaunch {
  return {
    origin: "direct",
    headline,
    context: opts?.context,
    eventId: opts?.eventId,
  };
}

/**
 * Opening an inbox candidate must never start a provider call — the operator
 * sees what the run would cover first.  Every other origin keeps the existing
 * behaviour, where arriving on the analysis surface IS the requested action.
 */
export function shouldAutoSubmit(launch: AnalysisLaunch): boolean {
  return launch.origin !== "inbox";
}

export function analysisActionFor(launch: AnalysisLaunch): AnalysisAction {
  if (launch.origin !== "inbox") return "run_paid";
  if (launch.link.status === "conflict") return "blocked_conflict";
  if (launch.link.status === "analyzed" && launch.link.analysisEventId !== null) {
    return "open_saved";
  }
  return "run_paid";
}

/**
 * Build the request the browser actually sends, or `null` when the requested
 * action cannot be honestly served (a conflict, or a saved read with no saved
 * id).  `null` means send nothing — never fall back to a paid run.
 */
export function analyzeRequestFor(
  launch: AnalysisLaunch,
  action: AnalysisAction,
): AnalyzeRequest | null {
  if (action === "blocked_conflict") return null;

  if (launch.origin === "inbox") {
    if (launch.link.status === "conflict") return null;
    if (action === "open_saved") {
      if (launch.link.analysisEventId === null) return null;
      return {
        headline: launch.headline,
        event_context: launch.context,
        event_id: launch.link.analysisEventId,
        confirm_paid: false,
      };
    }
    return {
      headline: launch.headline,
      event_context: launch.context,
      candidate_id: launch.candidate.candidate_id,
      parent_cluster_id: launch.candidate.parent_cluster_id,
      title_key: launch.candidate.title_key,
      confirm_paid: true,
    };
  }

  return {
    headline: launch.headline,
    event_context: launch.context,
    event_id: launch.eventId,
    confirm_paid: action === "run_paid",
  };
}
