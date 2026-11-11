// Pure route parsing. A malformed address is a Not Found page, never an exception.

export type Route =
  | { page: "index" }
  | { page: "method" }
  | { page: "dossier"; id: string }
  | { page: "library" }
  | { page: "library-case"; id: string }
  | { page: "historical-case"; id: string }
  | { page: "research"; id: string }
  | { page: "analyses" }
  | { page: "bis-snapshot" }
  | { page: "market-context" }
  | { page: "market-context-event"; kind: "inbox" | "capture"; id: string }
  | { page: "event-overview"; kind: "inbox" | "capture"; id: string }
  | { page: "research-analysis"; captureId: string }
  | { page: "hypotheses" }
  | { page: "hypothesis"; id: string }
  | { page: "hypothesis-assessment"; id: string; evaluationId: string }
  | { page: "hypothesis-dossier"; id: string; evaluationId: string }
  | { page: "findings" }
  | { page: "findings-occasion"; day: string }
  | { page: "findings-g17" }
  | { page: "thesis"; id: string; version: number | null }
  /** The copper tools: the coverage calculator and the producer comparison, beside the copper thesis. */
  | { page: "copper-tools" }
  /** The copper event chains: past events, the sources' own words, and the owner's review and reading. Admin only. */
  | { page: "copper-events" }
  /** The copper desk: the copper pages, the publication comparisons and the owner's research notes. Admin only. */
  | { page: "copper-desk" }
  /** One comparison of two retained publications, with the owner's notes on it. Admin only. */
  | { page: "copper-comparison"; id: string }
  /** The metals comparison: production, reserves and their concentration for the metals the reader picks. */
  | { page: "metals" }
  /** The fuels reference page: Brent spot, the NY Harbor 3-2-1 crack and their sources; personal and educational. */
  | { page: "fuels" }
  /** The FCX company page: how the copper price reaches Freeport-McMoRan's cash flow; private, admin only. */
  | { page: "company" }
  | { page: "not-found"; reason: "unknown" | "malformed" };

const DOSSIER_PATH = /^\/h\/([^/]+)\/?$/;
const LIBRARY_CASE_PATH = /^\/library\/([^/]+)\/?$/;
/** A historical case of Related Cases, listed in the case library apart from its release cases. */
const HISTORICAL_CASE_PATH = /^\/library\/historical\/([^/]+)\/?$/;
/** A research view: a retrospective comparison of selected retained publications, listed in the case library. */
const RESEARCH_PATH = /^\/library\/research\/([^/]+)\/?$/;
const CONTEXT_EVENT_PATH = /^\/market-context\/(inbox|capture)\/([^/]+)\/?$/;
const HYPOTHESIS_PATH = /^\/hypotheses\/([^/]+)\/?$/;
/** One recorded assessment of a frozen hypothesis, or its prepared Dossier (not the research Dossier at /h/:id). */
/** One dated occasion of the Treasury findings pilot. */
const OCCASION_PATH = /^\/findings\/(\d{4}-\d{2}-\d{2})\/?$/;
const RECORD_PATH = /^\/hypotheses\/([^/]+)\/(assessments|dossiers)\/([^/]+)\/?$/;
/** The private event overview; not the research Dossier at /h/:id. */
export const OVERVIEW_PATH = /^\/events\/(inbox|capture)\/([^/]+)\/?$/;
/** A saved event's evidence-first research analysis: its own request, result and review. */
const RESEARCH_ANALYSIS_PATH = /^\/events\/capture\/([^/]+)\/research\/?$/;
/** A committed thesis at its latest version, or at one named version (1 to 9999, ASCII digits, no leading zero). */
const THESIS_PATH = /^\/theses\/([^/]+)(?:\/versions\/([^/]+))?\/?$/;
const THESIS_VERSION = /^[1-9][0-9]{0,3}$/;
/** One publication comparison under the copper desk; its id is lower-case words joined by single hyphens. */
const COMPARISON_PATH = /^\/copper\/comparisons\/([^/]+)\/?$/;
const COMPARISON_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** decodeURIComponent, except that invalid percent escapes or UTF-8 sequences return null. */
export function safeDecode(segment: string): string | null {
  try {
    return decodeURIComponent(segment);
  } catch (error) {
    if (error instanceof URIError) return null;
    throw error;
  }
}

export function matchRoute(pathname: string): Route {
  if (pathname === "/") return { page: "index" };
  if (pathname === "/method" || pathname === "/method/") return { page: "method" };
  if (pathname === "/library" || pathname === "/library/") return { page: "library" };
  if (pathname === "/analyses" || pathname === "/analyses/") return { page: "analyses" };
  /** The retained BIS snapshot, browsed and imported into the Event Inbox; not a live feed. */
  if (pathname === "/inbox/bis-snapshot" || pathname === "/inbox/bis-snapshot/") return { page: "bis-snapshot" };
  if (pathname === "/market-context" || pathname === "/market-context/") return { page: "market-context" };
  if (pathname === "/fuels" || pathname === "/fuels/") return { page: "fuels" };
  if (pathname === "/hypotheses" || pathname === "/hypotheses/") return { page: "hypotheses" };
  if (pathname === "/findings" || pathname === "/findings/") return { page: "findings" };
  if (pathname === "/findings/g17" || pathname === "/findings/g17/") return { page: "findings-g17" };
  const occasion = OCCASION_PATH.exec(pathname);
  if (occasion) return { page: "findings-occasion", day: occasion[1] };
  if (pathname === "/theses/copper/tools" || pathname === "/theses/copper/tools/") return { page: "copper-tools" };
  if (pathname === "/theses/copper/events" || pathname === "/theses/copper/events/") return { page: "copper-events" };
  if (pathname === "/copper" || pathname === "/copper/") return { page: "copper-desk" };
  const comparison = COMPARISON_PATH.exec(pathname);
  if (comparison) {
    const comparisonId = safeDecode(comparison[1]);
    if (comparisonId === null) return { page: "not-found", reason: "malformed" };
    return COMPARISON_ID.test(comparisonId) ? { page: "copper-comparison", id: comparisonId }
      : { page: "not-found", reason: "unknown" };
  }
  if (pathname === "/metals" || pathname === "/metals/") return { page: "metals" };
  if (pathname === "/companies/fcx" || pathname === "/companies/fcx/") return { page: "company" };
  const thesis = THESIS_PATH.exec(pathname);
  if (thesis) {
    const thesisId = safeDecode(thesis[1]);
    const version = thesis[2] === undefined ? null : safeDecode(thesis[2]);
    if (thesisId === null || (thesis[2] !== undefined && (version === null || !THESIS_VERSION.test(version)))) {
      return { page: "not-found", reason: "malformed" };
    }
    return { page: "thesis", id: thesisId, version: version === null ? null : Number(version) };
  }
  const record = RECORD_PATH.exec(pathname);
  if (record) {
    const hypothesisId = safeDecode(record[1]);
    const evaluationId = safeDecode(record[3]);
    if (hypothesisId === null || evaluationId === null) return { page: "not-found", reason: "malformed" };
    return { page: record[2] === "assessments" ? "hypothesis-assessment" : "hypothesis-dossier", id: hypothesisId,
             evaluationId };
  }
  const frozen = HYPOTHESIS_PATH.exec(pathname);
  if (frozen) {
    const hypothesisId = safeDecode(frozen[1]);
    return hypothesisId === null ? { page: "not-found", reason: "malformed" } : { page: "hypothesis", id: hypothesisId };
  }
  const contextEvent = CONTEXT_EVENT_PATH.exec(pathname);
  if (contextEvent) {
    const eventId = safeDecode(contextEvent[2]);
    return eventId === null ? { page: "not-found", reason: "malformed" }
      : { page: "market-context-event", kind: contextEvent[1] as "inbox" | "capture", id: eventId };
  }
  const analysis = RESEARCH_ANALYSIS_PATH.exec(pathname);
  if (analysis) {
    const captureId = safeDecode(analysis[1]);
    return captureId === null ? { page: "not-found", reason: "malformed" } : { page: "research-analysis", captureId };
  }
  const overview = OVERVIEW_PATH.exec(pathname);
  if (overview) {
    const eventId = safeDecode(overview[2]);
    return eventId === null ? { page: "not-found", reason: "malformed" }
      : { page: "event-overview", kind: overview[1] as "inbox" | "capture", id: eventId };
  }
  const research = RESEARCH_PATH.exec(pathname)?.[1];
  if (research !== undefined) {
    const researchId = safeDecode(research);
    return researchId === null ? { page: "not-found", reason: "malformed" } : { page: "research", id: researchId };
  }
  const historical = HISTORICAL_CASE_PATH.exec(pathname)?.[1];
  if (historical !== undefined) {
    const caseId = safeDecode(historical);
    return caseId === null ? { page: "not-found", reason: "malformed" } : { page: "historical-case", id: caseId };
  }
  const caseSegment = LIBRARY_CASE_PATH.exec(pathname)?.[1];
  if (caseSegment !== undefined) {
    const caseId = safeDecode(caseSegment);
    return caseId === null ? { page: "not-found", reason: "malformed" } : { page: "library-case", id: caseId };
  }
  const segment = DOSSIER_PATH.exec(pathname)?.[1];
  if (segment === undefined) return { page: "not-found", reason: "unknown" };
  const id = safeDecode(segment);
  return id === null ? { page: "not-found", reason: "malformed" } : { page: "dossier", id };
}

/** The ?leg= selection; URLSearchParams never throws on malformed escapes. */
export function requestedLeg(search: string): string | null {
  return new URLSearchParams(search).get("leg");
}
