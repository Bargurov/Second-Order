// The copper research view (second_order/copper_research_view.py, copper-research-view-0.1): the copper desk's page
// lines, the publication comparisons and the owner's research notes, with the one owner save beside them
// (second_order/copper_research_api.py). The reply is read fail-closed, as the event chains are (eventChains.ts): the
// reader recomputes what the server guarantees and refuses the whole reply, naming the place and rule and never the
// value, when a served field breaks one. No row computes a change between its two lines (the owner's clarification of
// 2026-11-10): a row holds exactly its fields, so one that carries a change is refused, and an arrow is refused in the
// assistant's text and in the served problems and reasons; the owner's words and source wording are never scanned for
// one. A save is one POST; a lost reply is settled from the saved notes (`settleNote`), never by sending again.
import type { Loaded } from "./api.ts";
import { accountBinding } from "./admin/adminApi.ts";
import { maskedText, type Account, type Action, type BasisDocument, type DocumentState } from "./eventChains.ts";

export const COPPER_RESEARCH_VIEW_VERSION = "copper-research-view-0.1";
export const RESEARCH_NOTE_HEADER = "X-Second-Order-Research-Note";
export const DESK_PATH = "/copper";
export const MAX_NOTE = 2000;
export const MAX_EXPECTATION = 500;
export const MAX_QUESTION = 280;
const BASE = "/api/theses/copper/research";
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

export type SubjectKind = "comparison" | "chain" | "thesis";
export type SameMeasure = "not_applicable" | "not_established" | "no";
export type ComparisonState = "unavailable" | "needs_revalidation" | "evidence_changed" | "available";
export type About = { kind: SubjectKind; id: string };
export type DeskPage = { id: string; title: string; path: string; what: string; status: string | null;
  problem: string | null };
export type ListedDocument = { ref: string; name: string; state: DocumentState };
export type Publication = { ref: string; name: string; title: string; form: string; dated: string; dated_as: string;
  state: DocumentState; record: string };
export type RowSide = { ref: string; quote: string | null; where: string; document: ListedDocument; state: string;
  problem: string | null };
export type ComparisonRow = { id: string; label: string; same_measure: SameMeasure; sentence: string;
  note: string | null; note_withheld: boolean; earlier: RowSide; later: RowSide };
export type PriceFigure = { id: string; label: string | null;
  period: { label: string; start: string; end: string } | null; display: string | null; unit: string | null;
  source: { ref: string; name: string } | null; state: "available" | "withheld"; problem: string | null };
export type Prices = { figures: PriceFigure[]; covered_to: string | null; text: string };
export type ComparisonView = {
  id: string; title: string; latest_version: number; published_on: string; sha256: string; historical: boolean;
  historical_note: string | null; prepared_by: string; ai_assisted: boolean; state: ComparisonState;
  reasons: string[];
  earlier: Publication; later: Publication; rows: ComparisonRow[]; prices: Prices; documents: ListedDocument[];
};
export type Subject = About & { title: string; version: number; sha256: string; state: string; reasons: string[] };
export type Expectation = { text: string; check_by: string | null; state: "not_yet_checked"; status: string };
type Versioned = { id: string; sha256: string; version: number };
export type NoteBasis = { comparison?: Versioned; chain?: Versioned; thesis?: Versioned; evidence_sha256?: string };
export type NoteView = {
  note_id: string; parent_note_id: string | null; sequence: number; about: About; subject_title: string | null;
  follows: string | null; followed_by: string | null; text: string; expectation: Expectation | null;
  question: string | null; account: Account; saved_at: string; basis: NoteBasis; basis_documents: BasisDocument[];
  masked: boolean; steps: number; mask_reason: string | null; state: "current" | "earlier_basis"; differs: string[];
  hindsight: string | null;
};
export type Notes = { state: "valid" | "invalid"; problem: string | null; latest: string | null; items: NoteView[] };
export type CopperResearchView = {
  view_version: string; provider_called: false; desk: { pages: DeskPage[] }; comparisons: ComparisonView[];
  subjects: Subject[]; notes: Notes;
};

/** The five copper pages the desk links to, in order (copper_research_view.PAGES): each id and its path. */
export const DESK_PAGES: readonly (readonly [string, string])[] = [["thesis", "/theses/copper"],
  ["tools", "/theses/copper/tools"], ["fcx", "/companies/fcx"], ["metals", "/metals"],
  ["events", "/theses/copper/events"]];
/** A row's fixed sentence by its `same_measure` (copper_research_view.SAME_MEASURE). */
export const SAME_MEASURE: Record<SameMeasure, string> = {
  not_applicable: "Two statements, each shown as written.",
  not_established: "No retained source establishes that the two lines measure the same thing. No change is computed "
    + "between them.",
  no: "The two lines are not the same measure. No change is computed between them.",
};
export const HISTORICAL = "Historical: both publications were already retained when this comparison was prepared.";
const NOT_CHECKED = "Not yet checked: nothing retained after this note was saved has been compared with it.";
const PASSED = " Its check-by date has passed.";
const NO_PRICES = "No retained price can be shown on this machine.";
const pricesTo = (day: string) => `Retained prices cover up to ${day}. No retained price covers a later date.`;
const hindsightOf = (saved: string, later: string) =>
  `Written after both publications were known: saved on ${saved}, the later publication is dated ${later}.`;

// ---------------------------------------------------------------- the reader

class Refused extends Error {}
type Rec = Record<string, unknown>;

function need(ok: unknown, where: string, rule: string): asserts ok {
  if (!ok) throw new Refused(`${where}: ${rule}`);
}
const SHA = /^[0-9a-f]{64}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const DIGIT = /[0-9]/;
const ARROW = /→|⟶|->/;
/** The saving day and the later publication's day of a hindsight sentence, or null when it is not that sentence. */
function hindsightDays(value: unknown): [string, string] | null {
  if (typeof value !== "string") return null;
  const days = value.match(/\d{4}-\d{2}-\d{2}/g) ?? [];
  return days.length === 2 && value === hindsightOf(days[0], days[1]) ? [days[0], days[1]] : null;
}
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const isNullText = (value: unknown): value is string | null => value === null || isText(value);
const isCount = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value >= 1;
const isSha = (value: unknown): value is string => typeof value === "string" && SHA.test(value);
const isDay = (value: unknown): value is string => typeof value === "string" && DAY.test(value);
const isId = (value: unknown): value is string => typeof value === "string" && ID.test(value);
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const sameAbout = (a: Rec | About, b: About) => a.kind === b.kind && a.id === b.id;

function rec(value: unknown, keys: readonly string[], where: string): Rec {
  need(isRec(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)),
    where, "does not have exactly the expected fields");
  return value;
}
function list(value: unknown, where: string): unknown[] {
  need(Array.isArray(value), where, "is not a list");
  return value;
}
/** Served reasons: a list of non-empty texts, none with an arrow. */
function texts(value: unknown, where: string): string[] {
  need(Array.isArray(value) && value.every(isText), where, "is not a list of reasons");
  value.forEach((item, at) => noArrow(item, `${where}[${at}]`));
  return value;
}
/** Assistant text and served problems or reasons: never an arrow (the owner's words and quotes are not checked). */
function noArrow(value: unknown, where: string): void {
  need(typeof value !== "string" || !ARROW.test(value), where, "holds an arrow character");
}

const KINDS: readonly string[] = ["comparison", "chain", "thesis"];
const SIDES = ["earlier", "later"] as const;
const DOCUMENT_STATES: readonly string[] = ["verified", "changed", "missing", "superseded", "unreadable"];
const RECORD_STATES: readonly string[] = ["same", "changed", "gone", "unreadable"];
const SIDE_RECORD_STATES: readonly string[] = ["record_changed", "record_gone", "record_unreadable"];
const COMPARISON_STATES: readonly ComparisonState[] = ["unavailable", "needs_revalidation", "evidence_changed",
  "available"];
const SUBJECT_STATES: Record<SubjectKind, readonly string[]> = {
  thesis: ["unavailable", "needs_revalidation", "available"],
  chain: ["unavailable", "needs_revalidation", "evidence_changed", "thesis_newer", "available"],
  comparison: COMPARISON_STATES,
};
const BASIS_FIELDS: Record<SubjectKind, readonly string[]> = {
  comparison: ["comparison", "evidence_sha256"], chain: ["chain", "evidence_sha256", "thesis"], thesis: ["thesis"],
};

function documentOf(value: unknown, where: string): ListedDocument {
  const found = rec(value, ["ref", "name", "state"], where);
  need(isText(found.ref) && isText(found.name) && DOCUMENT_STATES.includes(found.state as string), where,
    "is not a document state");
  return found as unknown as ListedDocument;
}

function pagesOf(value: unknown): void {
  const desk = rec(value, ["pages"], "desk");
  const pages = list(desk.pages, "desk.pages");
  need(pages.length === DESK_PAGES.length, "desk.pages", "is not the five copper pages");
  pages.forEach((item, at) => {
    const where = `desk.pages[${at}]`;
    const page = rec(item, ["id", "title", "path", "what", "status", "problem"], where);
    need(page.id === DESK_PAGES[at][0] && page.path === DESK_PAGES[at][1], where,
      "is not the expected page at its expected path");
    need(isText(page.title) && isText(page.what) && isNullText(page.status) && isNullText(page.problem), where,
      "holds a field that is not text");
    need(page.status === null || page.problem === null, where, "holds both a status line and a problem");
    noArrow(page.problem, `${where}.problem`);
  });
}

function publicationOf(value: unknown, where: string, documents: ListedDocument[]): Publication {
  const found = rec(value, ["ref", "name", "title", "form", "dated", "dated_as", "state", "record"], where);
  need(isText(found.ref) && isText(found.name) && isText(found.title) && isText(found.form) && isText(found.dated_as),
    where, "does not name its publication");
  need(isDay(found.dated), `${where}.dated`, "is not a date");
  need(DOCUMENT_STATES.includes(found.state as string) && RECORD_STATES.includes(found.record as string), where,
    "is not a publication state");
  const listed = documents.find((item) => item.ref === found.ref);
  need(found.state === (listed?.state ?? "missing"), `${where}.state`, "does not match the comparison's document list");
  return found as unknown as Publication;
}

/** One line of a row: the source's words only while its document verifies and its record is as it was pinned. */
function sideOf(value: unknown, where: string, publication: Publication): RowSide {
  const found = rec(value, ["ref", "quote", "where", "document", "state", "problem"], where);
  need(isText(found.ref) && isText(found.where) && isText(found.state), where, "does not name its passage");
  need(isNullText(found.quote) && isNullText(found.problem), where, "holds a field that is not text");
  noArrow(found.problem, `${where}.problem`);
  const document = documentOf(found.document, `${where}.document`);
  need(document.ref === publication.ref && document.state === publication.state, `${where}.document`,
    "is not its publication's document in its state");
  if (found.state !== "verified") {
    need(found.quote === null, where, "carries a quote while it is not verified");
    need(document.state !== "verified" ? found.state === document.state : SIDE_RECORD_STATES.includes(found.state),
      `${where}.state`, "does not follow from its document or is not a side state");
    need(isText(found.problem), `${where}.problem`, "does not say why the quote is withheld");
  } else {
    need(document.state === "verified", `${where}.state`, "is verified while its document is not");
    need(isText(found.quote), `${where}.quote`, "is missing although the side is verified");
    need(found.problem === null, `${where}.problem`, "is set on a verified side");
  }
  return found as unknown as RowSide;
}

function rowOf(value: unknown, where: string, comparison: ComparisonView): void {
  // Exactly these fields: a row has no field for a change between its two lines, so one that carries any is refused.
  const found = rec(value, ["id", "label", "same_measure", "sentence", "note", "note_withheld", "earlier", "later"],
    where);
  need(isText(found.id) && isText(found.label), where, "does not name its row");
  noArrow(found.label, `${where}.label`);
  need(!DIGIT.test(found.label), `${where}.label`, "holds a figure");
  need(typeof found.same_measure === "string" && Object.hasOwn(SAME_MEASURE, found.same_measure),
    `${where}.same_measure`, "is not one of the three answers");
  need(found.sentence === SAME_MEASURE[found.same_measure as SameMeasure], `${where}.sentence`,
    "is not the fixed sentence of its same_measure");
  const sides = SIDES.map((side) => sideOf(found[side], `${where}.${side}`, comparison[side]));
  const shown = sides.every((side) => side.state === "verified");
  need(isNullText(found.note) && typeof found.note_withheld === "boolean", `${where}.note`, "is not a note");
  noArrow(found.note, `${where}.note`);
  if (found.note_withheld) {
    need(found.note === null, `${where}.note`, "is shown although it is marked as withheld");
    need(!shown, `${where}.note_withheld`, "is set although both sides are verified");
  } else if (found.note === null) {
    need(found.same_measure === "not_applicable", `${where}.note`,
      "is missing from a row that says whether its lines are one measure");
  } else {
    // The note says what each line states, so the server withholds it with any line of its row that is withheld.
    need(shown, `${where}.note`, "is shown while one of its sides is not verified; it must be withheld");
  }
}

function pricesOf(value: unknown, where: string): void {
  const found = rec(value, ["figures", "covered_to", "text"], where);
  const ends: string[] = [];
  const figures = list(found.figures, `${where}.figures`);
  figures.forEach((item, at) => {
    const place = `${where}.figures[${at}]`;
    const one = rec(item, ["id", "label", "period", "display", "unit", "source", "state", "problem"], place);
    need(isText(one.id) && isNullText(one.label) && isNullText(one.unit) && isNullText(one.display)
      && isNullText(one.problem), place, "holds a field that is not text");
    noArrow(one.problem, `${place}.problem`);
    if (one.source !== null) {
      const source = rec(one.source, ["ref", "name"], `${place}.source`);
      need(isText(source.ref) && isText(source.name), `${place}.source`, "does not name its source");
    }
    if (one.period !== null) {
      const period = rec(one.period, ["label", "start", "end"], `${place}.period`);
      need(isText(period.label) && isDay(period.start) && isDay(period.end) && period.start <= period.end,
        `${place}.period`, "is not a dated period");
    }
    if (one.state === "available") {
      need(isText(one.display) && one.period !== null, place, "is available without its display and its period");
      need(isText(one.label) && isText(one.unit) && one.source !== null && one.problem === null, place,
        "is available without its label, unit and source, or with a problem");
      ends.push((one.period as { end: string }).end);
    } else {
      need(one.state === "withheld", `${place}.state`, "is not a figure state");
      need(one.display === null, `${place}.display`, "is shown although the figure is withheld");
      need(isText(one.problem), `${place}.problem`, "does not say why the figure is withheld");
    }
  });
  need(new Set(figures.map((item) => (item as Rec).id)).size === figures.length, `${where}.figures`,
    "repeats a figure");
  const covered = ends.length === 0 ? null : ends.reduce((latest, end) => (end > latest ? end : latest));
  need(found.covered_to === covered, `${where}.covered_to`, "is not the latest period end of the available figures");
  need(found.text === (covered === null ? NO_PRICES : pricesTo(covered)), `${where}.text`,
    "is not the fixed sentence for its covered_to");
}

/** The state the documents and the lines alone give, in the server's rule order. */
function derivedState(comparison: ComparisonView): ComparisonState {
  const documents = [...comparison.documents, comparison.earlier, comparison.later];
  if (documents.some((item) => item.state === "missing" || item.state === "unreadable")) return "unavailable";
  if (documents.some((item) => item.state !== "verified")) return "needs_revalidation";
  const changed = (record: string) => record === "changed" || record === "gone";
  if (changed(comparison.earlier.record) || changed(comparison.later.record)
    || comparison.rows.some((row) => row.earlier.state !== "verified" || row.later.state !== "verified")) {
    return "evidence_changed";
  }
  return "available";
}

function comparisonOf(value: unknown, where: string): ComparisonView {
  const found = rec(value, ["id", "title", "latest_version", "published_on", "sha256", "historical", "historical_note",
    "prepared_by", "ai_assisted", "state", "reasons", "earlier", "later", "rows", "prices", "documents"], where);
  need(isId(found.id) && isText(found.title) && isCount(found.latest_version) && isText(found.published_on)
    && isSha(found.sha256), where, "does not name its comparison");
  const comparison = found as unknown as ComparisonView;
  where = `comparisons[${found.id}]`;
  noArrow(found.title, `${where}.title`);
  need(typeof found.historical === "boolean" && found.historical_note === (found.historical ? HISTORICAL : null),
    `${where}.historical_note`, "is not the fixed sentence of a historical comparison");
  // The page's fixed mark says the assistant prepared it: the flag says so; who prepared it is named in free text.
  need(found.ai_assisted === true, `${where}.ai_assisted`, "is not marked as prepared by the assistant");
  need(isText(found.prepared_by), `${where}.prepared_by`, "does not say who prepared it");
  need(COMPARISON_STATES.includes(found.state as ComparisonState), `${where}.state`, "is not a comparison state");
  need((texts(found.reasons, `${where}.reasons`).length === 0) === (found.state === "available"), `${where}.reasons`,
    "does not match the comparison's state");
  const documents = list(found.documents, `${where}.documents`)
    .map((item, at) => documentOf(item, `${where}.documents[${at}]`));
  SIDES.forEach((side) => publicationOf(found[side], `${where}.${side}`, documents));
  const rows = list(found.rows, `${where}.rows`);
  need(rows.length > 0, `${where}.rows`, "is empty");
  rows.forEach((row, at) => rowOf(row, `${where}.rows[${at}]`, comparison));
  need(new Set(comparison.rows.map((row) => row.id)).size === rows.length, `${where}.rows`, "repeats a row");
  need(COMPARISON_STATES.indexOf(comparison.state) <= COMPARISON_STATES.indexOf(derivedState(comparison)),
    `${where}.state`, "is less severe than its documents and lines give");
  pricesOf(found.prices, `${where}.prices`);
  return comparison;
}

function subjectOf(value: unknown, where: string): Subject {
  const found = rec(value, ["kind", "id", "title", "version", "sha256", "state", "reasons"], where);
  need(KINDS.includes(found.kind as string) && isId(found.id), where, "does not name a subject");
  where = `subjects[${found.kind}:${found.id}]`;
  need(found.kind !== "thesis" || found.id === "copper", where, "is not the copper thesis");
  need(isText(found.title) && isCount(found.version) && isSha(found.sha256), where, "does not name its version");
  need(SUBJECT_STATES[found.kind as SubjectKind].includes(found.state as string), `${where}.state`,
    "is not a state of its kind");
  need((texts(found.reasons, `${where}.reasons`).length === 0) === (found.state === "available"), `${where}.reasons`,
    "does not match the subject's state");
  return found as unknown as Subject;
}

function versioned(value: unknown, where: string): Versioned {
  const found = rec(value, ["id", "sha256", "version"], where);
  need(isText(found.id) && isSha(found.sha256) && isCount(found.version), where, "does not name a version");
  return found as unknown as Versioned;
}

/** One saved note as served: its place in the history, its subject, its state now, and the masking its basis
 * documents require (by `steps`, the step count of the chain version a chain note names; 0 for other subjects). */
function noteOf(value: unknown, index: number, previous: string | null, view: CopperResearchView): NoteView {
  let where = `notes.items[${index}]`;
  const found = rec(value, ["note_id", "parent_note_id", "sequence", "about", "subject_title", "follows", "followed_by",
    "text", "expectation", "question", "account", "saved_at", "basis", "basis_documents", "masked", "steps",
    "mask_reason", "state", "differs", "hindsight"], where);
  need(isSha(found.note_id), `${where}.note_id`, "is not a content id");
  need(found.parent_note_id === previous, `${where}.parent_note_id`, "is not the note before it");
  need(found.sequence === index + 1, `${where}.sequence`, "is not its position in the history");
  const about = rec(found.about, ["kind", "id"], `${where}.about`);
  need(KINDS.includes(about.kind as string) && isId(about.id), `${where}.about`, "does not name a subject");
  const kind = about.kind as SubjectKind;
  need(isText(found.text) && isNullText(found.question), where, "does not hold its text");
  need(typeof found.saved_at === "string" && /^\d{4}-\d{2}-\d{2}T/.test(found.saved_at)
    && !Number.isNaN(Date.parse(found.saved_at)), `${where}.saved_at`, "is not a time");
  const account = rec(found.account, ["user_id", "username"], `${where}.account`);
  need(isText(account.user_id) && isText(account.username), `${where}.account`, "is not an account");
  need(found.follows === null || isSha(found.follows), `${where}.follows`, "is not a note id");
  need(found.followed_by === null || isSha(found.followed_by), `${where}.followed_by`, "is not a note id");

  const basis = rec(found.basis, BASIS_FIELDS[kind], `${where}.basis`);
  const named = versioned(basis[kind], `${where}.basis.${kind}`);
  need(named.id === about.id, `${where}.basis.${kind}`, "does not name the note's subject");
  need(!("evidence_sha256" in basis) || isSha(basis.evidence_sha256), `${where}.basis.evidence_sha256`,
    "is not a SHA-256");
  if (kind === "chain") versioned(basis.thesis, `${where}.basis.thesis`);

  const documents = list(found.basis_documents, `${where}.basis_documents`);
  need(documents.length > 0, `${where}.basis_documents`, "is empty");
  const failing = documents.map((item, at) => {
    const one = rec(item, ["ref", "name", "state", "detail"], `${where}.basis_documents[${at}]`);
    need(isText(one.ref) && isText(one.name) && isText(one.detail) && DOCUMENT_STATES.includes(one.state as string),
      `${where}.basis_documents[${at}]`, "is not a document state");
    return one.state !== "verified";
  }).some(Boolean);
  need(found.masked === failing, `${where}.masked`, "does not follow from the basis documents' states");
  need(failing ? isText(found.mask_reason) : found.mask_reason === null, `${where}.mask_reason`,
    "does not follow from the basis documents' states");
  noArrow(found.mask_reason, `${where}.mask_reason`);
  need(typeof found.steps === "number" && Number.isInteger(found.steps) && found.steps >= 0
    && (kind === "chain" || found.steps === 0), `${where}.steps`, "is not a step count of the note's subject");
  const unmasked = (text: string) => !failing || maskedText(text, found.steps as number) === text;
  const still = "still holds a figure outside step references while a basis document fails";
  need(unmasked(found.text), `${where}.text`, still);
  need(found.question === null || unmasked(found.question), `${where}.question`, still);
  if (found.expectation !== null) {
    const expectation = rec(found.expectation, ["text", "check_by", "state", "status"], `${where}.expectation`);
    need(isText(expectation.text) && (expectation.check_by === null || isDay(expectation.check_by)),
      `${where}.expectation`, "is not a text with a check-by date or none");
    need(expectation.state === "not_yet_checked", `${where}.expectation.state`, "is not not_yet_checked");
    need(expectation.status === NOT_CHECKED || (expectation.status === NOT_CHECKED + PASSED
      && expectation.check_by !== null), `${where}.expectation.status`, "is not the fixed line of an unchecked one");
    need(unmasked(expectation.text), `${where}.expectation.text`, still);
  }

  const subject = view.subjects.find((item) => item.kind === kind && item.id === about.id);
  need(found.subject_title === (subject?.title ?? null), `${where}.subject_title`, "is not its subject's title");
  need(found.state === "current" || found.state === "earlier_basis", `${where}.state`, "is not a note state");
  const differs = texts(found.differs, `${where}.differs`);
  need((found.state === "current") === (differs.length === 0), `${where}.state`,
    "is current with reasons, or on an earlier basis without any");
  need(subject === undefined || subject.sha256 !== named.sha256 ? differs.length > 0 : same(differs, subject.reasons),
    `${where}.differs`, "does not follow from its subject as it is now");

  where = `${where}.hindsight`;
  const saved = found.saved_at.slice(0, 10);
  if (found.hindsight !== null) {
    const days = hindsightDays(found.hindsight);
    need(kind === "comparison" && days !== null && days[0] === saved && days[0] >= days[1], where,
      "is not the fixed sentence of a comparison note saved after its later publication");
  }
  const comparison = view.comparisons.find((item) => kind === "comparison" && item.id === about.id);
  if (comparison !== undefined && comparison.sha256 === named.sha256 && comparison.latest_version === named.version) {
    const later = comparison.later.dated;
    need(found.hindsight === (saved >= later ? hindsightOf(saved, later) : null), where,
      "does not follow from the saving day and the later publication's date");
  }
  return found as unknown as NoteView;
}

function notesOf(value: unknown, view: CopperResearchView): void {
  const found = rec(value, ["state", "problem", "latest", "items"], "notes");
  need(found.state === "valid" || found.state === "invalid", "notes.state", "is not a history state");
  need(found.state === "invalid" ? isText(found.problem) : found.problem === null, "notes.problem",
    "does not follow from the history's state");
  noArrow(found.problem, "notes.problem");
  const items = list(found.items, "notes.items");
  need(found.state === "valid" || (items.length === 0 && found.latest === null), "notes.items",
    "holds notes or a latest id in a history that cannot be verified");
  let previous: string | null = null;
  const notes = items.map((item, at) => {
    const note = noteOf(item, at, previous, view);
    previous = note.note_id;
    return note;
  });
  need(found.latest === previous, "notes.latest", "is not the last note's id");
  const followed = new Map<string, string>();
  notes.forEach((note, at) => {
    if (note.follows === null) return;
    const earlier = notes.slice(0, at).find((item) => item.note_id === note.follows);
    need(earlier !== undefined && sameAbout(earlier.about, note.about), `notes.items[${at}].follows`,
      "is not an earlier note about the same subject");
    followed.set(note.follows, note.note_id);
  });
  notes.forEach((note, at) => need(note.followed_by === (followed.get(note.note_id) ?? null),
    `notes.items[${at}].followed_by`, "is not the note that follows it"));
}

/** Why a served reply cannot be read, naming the place and rule (never a value), or null when it can. */
export function copperResearchRefusal(body: unknown): string | null {
  try {
    const found = rec(body, ["view_version", "provider_called", "desk", "comparisons", "subjects", "notes"], "reply");
    need(found.view_version === COPPER_RESEARCH_VIEW_VERSION, "view_version", "is not the version this page reads");
    need(found.provider_called === false, "provider_called", "is not false");
    const view = found as unknown as CopperResearchView;
    pagesOf(found.desk);
    const comparisons = list(found.comparisons, "comparisons")
      .map((item, at) => comparisonOf(item, `comparisons[${at}]`));
    need(new Set(comparisons.map((item) => item.id)).size === comparisons.length, "comparisons",
      "repeats a comparison");
    const subjects = list(found.subjects, "subjects").map((item, at) => subjectOf(item, `subjects[${at}]`));
    need(new Set(subjects.map(subjectKey)).size === subjects.length, "subjects", "repeats a subject");
    // A note can be written about each comparison, and its form opens or closes by the comparison's own state.
    for (const subject of subjects.filter((item) => item.kind === "comparison")) {
      const about = comparisons.find((item) => item.id === subject.id);
      need(about !== undefined && about.title === subject.title && about.latest_version === subject.version
        && about.sha256 === subject.sha256 && about.state === subject.state && same(about.reasons, subject.reasons),
      `subjects[comparison:${subject.id}]`, "does not match its comparison");
    }
    for (const item of comparisons) {
      need(subjects.some((subject) => subject.kind === "comparison" && subject.id === item.id),
        `comparisons[${item.id}]`, "is not among the subjects");
    }
    notesOf(found.notes, view);
    return null;
  } catch (error) {
    if (error instanceof Refused) return error.message;
    if (error instanceof TypeError || error instanceof RangeError) return "reply: is not shaped as expected";
    throw error;
  }
}

export async function fetchCopperResearch(signal?: AbortSignal): Promise<Loaded<CopperResearchView>> {
  let response: Response;
  try {
    response = await fetch(BASE, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  const message = isRec(body) && typeof body.detail === "string" ? body.detail
    : `Unexpected response (${response.status}).`;
  if (response.status === 404) return { state: "missing", message };
  if (!response.ok) return { state: "error", message };
  const refusal = copperResearchRefusal(body);
  return refusal === null ? { state: "ready", data: body as CopperResearchView }
    : { state: "error", message: `The reply could not be read by this page (${refusal}).` };
}

// ---------------------------------------------------------------- the save

/** What the note form holds: the three texts as typed, the check-by date ("" or YYYY-MM-DD) and the followed note. */
export type NoteDraft = { text: string; expectation: string; checkBy: string; question: string;
  follows: string | null };
export type NoteBody = { parent_note_id: string | null; about: About; subject_sha256: string; follows: string | null;
  text: string; expectation: { text: string; check_by: string | null } | null; question: string | null };
export type SavedNote = { record_version: string; note_id: string; sequence: number; account: Account;
  saved_at: string } & Rec;
export type NoteReply = { record: SavedNote };

/** The exact body of a note save (research_notes.REQUEST_FIELDS): each text trimmed as the server stores it, an empty
 * expectation or question sent as null, and a check-by date only with an expectation. */
export function noteBody(notes: Notes, subject: Subject, draft: NoteDraft): NoteBody {
  const expectation = draft.expectation.trim();
  const question = draft.question.trim();
  return { parent_note_id: notes.latest, about: { kind: subject.kind, id: subject.id }, subject_sha256: subject.sha256,
    follows: draft.follows, text: draft.text.trim(),
    expectation: expectation === "" ? null
      : { text: expectation, check_by: draft.checkBy === "" ? null : draft.checkBy },
    question: question === "" ? null : question };
}

const UNREADABLE = "The reply could not be read as the note that was sent; check the saved notes before trying again.";

/** Whether a record the server returned is the note that was sent. */
function isSentNote(record: unknown, sent: NoteBody): record is SavedNote {
  if (!isRec(record) || !isRec(record.basis) || !isRec(record.account)) return false;
  const named = record.basis[sent.about.kind];
  const expectation = record.expectation;
  return isRec(named) && named.id === sent.about.id && named.sha256 === sent.subject_sha256
    && typeof record.note_id === "string" && typeof record.sequence === "number" && typeof record.saved_at === "string"
    && record.parent_note_id === sent.parent_note_id && isRec(record.about) && sameAbout(record.about, sent.about)
    && record.follows === sent.follows && record.text === sent.text && record.question === sent.question
    && (sent.expectation === null ? expectation === null : isRec(expectation)
      && expectation.text === sent.expectation.text && expectation.check_by === sent.expectation.check_by);
}

/** Save one note: one POST with the action header and the account binding. 201 with the sent note is "ready"; 409 with
 * exactly {detail, latest} is "blocked"; another 4xx is "failed"; a 5xx, a lost reply or one that cannot be read as the
 * sent note is "unconfirmed" and is never sent again from here. */
export async function saveNote(body: NoteBody): Promise<Action<NoteReply>> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/notes`, { method: "POST", body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", Accept: "application/json", [RESEARCH_NOTE_HEADER]: "1",
                 ...accountBinding() } });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server; nothing was sent again." };
  }
  const payload: unknown = await response.json().catch(() => null);
  const detail = isRec(payload) && typeof payload.detail === "string" ? payload.detail : null;
  if (response.status === 409) {
    const exact = isRec(payload) && Object.keys(payload).length === 2 && detail !== null
      && (payload.latest === null || typeof payload.latest === "string");
    return exact ? { state: "blocked", message: detail, latest: payload.latest as string | null }
      : { state: "unconfirmed", message: `Unexpected response (${response.status}).` };
  }
  if (!response.ok) {
    return { state: response.status >= 500 ? "unconfirmed" : "failed",
             message: detail ?? `Unexpected response (${response.status}).` };
  }
  if (response.status !== 201 || !isRec(payload) || Object.keys(payload).length !== 1
    || !isSentNote(payload.record, body)) return { state: "unconfirmed", message: UNREADABLE };
  return { state: "ready", status: 201, data: payload as NoteReply };
}

// ---------------------------------------------------------------- settling a lost reply

/** Saved text equals the sent text, or, while the note is masked, the sent text as the server masks it. */
const sameText = (note: NoteView, saved: string | null, sent: string | null): boolean =>
  saved === sent || (note.masked && saved !== null && sent !== null && maskedText(sent, note.steps) === saved);

/**
 * What the saved notes say about a save whose reply was lost. Only the note that follows the sent parent can be it,
 * and it is it only if its subject, the subject version it is bound to, the note it follows and its three texts are
 * what was sent: the parent alone never identifies a save. "saved": it is there (later notes may follow it).
 * "conflict": another note took that place. "not-saved": none follows the parent. "unverifiable": the saved notes
 * cannot be verified, so nothing is concluded and the save must not be sent again. Read-only: this never sends.
 */
export function settleNote(view: CopperResearchView, sent: NoteBody):
  "saved" | "conflict" | "not-saved" | "unverifiable" {
  if (view.notes.state === "invalid") return "unverifiable";
  const found = view.notes.items.find((item) => item.parent_note_id === sent.parent_note_id);
  if (found === undefined) return "not-saved";
  const expectation = found.expectation;
  const kept = sameAbout(found.about, sent.about) && found.basis[sent.about.kind]?.sha256 === sent.subject_sha256
    && found.follows === sent.follows && sameText(found, found.text, sent.text)
    && sameText(found, found.question, sent.question)
    && (expectation === null ? sent.expectation === null : sent.expectation !== null
      && expectation.check_by === sent.expectation.check_by
      && sameText(found, expectation.text, sent.expectation.text));
  return kept ? "saved" : "conflict";
}

// ---------------------------------------------------------------- plain rendering rules of the two pages

export const STATE_LABEL: Record<string, string> = {
  unavailable: "Unavailable", needs_revalidation: "Needs revalidation", evidence_changed: "Evidence changed",
  thesis_newer: "A newer thesis version exists", available: "Available",
};
const STATE_WORDS: Record<string, string> = {
  unavailable: "unavailable", needs_revalidation: "in need of revalidation",
  evidence_changed: "resting on changed evidence", thesis_newer: "behind a newer thesis version",
};
const KIND_LABEL: Record<SubjectKind, string> = { thesis: "Thesis", chain: "Chain", comparison: "Comparison" };

export const subjectKey = (about: About): string => `${about.kind}:${about.id}`;
export const comparisonPath = (id: string): string => `${DESK_PATH}/comparisons/${id}`;
/** A subject in the form's selector: "Thesis: <title>", "Chain: <title>" or "Comparison: <title>". */
export const subjectLabel = (subject: Subject): string => `${KIND_LABEL[subject.kind]}: ${subject.title}`;
/** The page that shows a note's subject: the comparison's own page, the event chains page or the thesis page. */
export const subjectPath = (about: About): string =>
  about.kind === "comparison" ? comparisonPath(about.id) : about.kind === "chain" ? "/theses/copper/events"
    : "/theses/copper";
/** "dated <date> (<dated_as>)", as the publication is dated in the research. */
export const datedLine = (publication: Publication): string => `dated ${publication.dated} (${publication.dated_as})`;
/** An available price figure as "<label>, <period> (<start> to <end>): <display> <unit>"; null for a withheld one. */
export const priceLine = (figure: PriceFigure): string | null =>
  figure.state !== "available" || figure.period === null ? null
    : `${figure.label}, ${figure.period.label} (${figure.period.start} to ${figure.period.end}): ${figure.display} `
      + `${figure.unit}`;
/** Why the form cannot send a note about this subject now, or null while it can. */
export const closedReason = (subject: Subject): string | null => subject.state === "available" ? null
  : `Notes are not accepted while the ${subject.kind} is ${STATE_WORDS[subject.state] ?? subject.state}`
    + `${subject.reasons.length > 0 ? `: ${subject.reasons[0]}` : ""}.`;
export const newestFirst = (notes: NoteView[]): NoteView[] => [...notes].reverse();
/** The notes about one subject, oldest first. */
export const notesAbout = (notes: Notes, about: About): NoteView[] =>
  notes.items.filter((note) => note.about.kind === about.kind && note.about.id === about.id);
/** The owner's latest note about a subject (the one a new note may follow), or null. */
export const latestNoteAbout = (notes: Notes, about: About): NoteView | null => notesAbout(notes, about).at(-1) ?? null;
/**
 * The notes whose question is still open, newest first. A question is closed by a later note about the same subject
 * that follows it, or that follows a note saved after it: the form can only follow the latest note on a subject, so a
 * question on an earlier note of that subject closes with it and can never be stranded.
 */
export function openQuestions(notes: Notes): NoteView[] {
  const sequence = new Map(notes.items.map((note) => [note.note_id, note.sequence]));
  const closed = (asked: NoteView): boolean => notes.items.some((later) => later.sequence > asked.sequence
    && later.about.kind === asked.about.kind && later.about.id === asked.about.id && later.follows !== null
    && (sequence.get(later.follows) ?? 0) >= asked.sequence);
  return newestFirst(notes.items.filter((note) => note.question !== null && !closed(note)));
}
