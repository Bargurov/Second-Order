// Copper event chains (second_order/event_chain_view.py, event-chains-view-0.1) and the two owner saves beside them
// (second_order/event_chain_api.py). The reply is read fail-closed: the reader recomputes what the server guarantees
// instead of trusting it (the withholding rules of the spec, section 6) and refuses the whole reply, naming the place
// and rule and never the value, when a served field breaks one. The steps are never joined by arrows, so an arrow is
// refused in the assistant's text (titles, labels, mechanisms, not-stated lines, change notes, the target note) and in
// the served problems and reasons; the owner's words and source wording are never scanned for one. A save is one POST;
// a lost reply is settled from the saved history (`settle`), never by sending again.
import type { Loaded } from "./api.ts";
import { accountBinding } from "./admin/adminApi.ts";

export const EVENT_CHAIN_VIEW_VERSION = "event-chains-view-0.1";
export const EVENT_CHAIN_HEADER = "X-Second-Order-Event-Chain";
export const FIGURE_WITHHELD = "[figure withheld]";
const BASE = "/api/theses/copper/event-chains";
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

export type Judgment = "supports" | "refutes" | "neither" | "not_sure";
export type Account = { user_id: string; username: string };
export type DocumentState = "verified" | "changed" | "missing" | "superseded" | "unreadable";
export type ChainState = "unavailable" | "needs_revalidation" | "evidence_changed" | "thesis_newer" | "available";
export type Basis = { chain: { id: string; sha256: string; version: number }; evidence_sha256: string | null;
  thesis: { id: string; sha256: string; version: number } };
export type BasisDocument = { ref: string; name: string; state: DocumentState; detail: string };
type Shared = { sequence: number; account: Account; saved_at: string; basis: Basis; basis_documents: BasisDocument[];
  masked: boolean; mask_reason: string | null; differs: string[] };
export type ReviewRecordView = Shared & { review_id: string; parent_review_id: string | null;
  status: "approved" | "needs_revision"; notes: string;
  state: "needs_revision" | "approved" | "approved_earlier_basis" };
export type ReadingRecordView = Shared & { reading_id: string; parent_reading_id: string | null; approval_id: string;
  target: { id: string; kind: string }; short_term: Judgment; long_term: Judgment; line: string;
  state: "current" | "earlier_basis" };
export type Step =
  | { kind: "stated"; label: string | null; ref: string; quote: string | null; pinned_quote: string | null;
      current_quote: string | null; where: string; pinned_where: string | null; current_where: string | null;
      document: { ref: string; name: string; state: DocumentState }; state: string; problem: string | null }
  | { kind: "not_stated"; text: string }
  | { kind: "mechanism"; id: string; text: string };
export type ChainHistory = {
  state: "valid" | "invalid"; problem: string | null; versions: Record<string, unknown>[];
  reviews: ReviewRecordView[]; readings: ReadingRecordView[];
};
export type ChainView = {
  id: string; title: string; latest_version: number; published_on: string; state: ChainState; reasons: string[];
  event: Record<string, unknown>; items: { ref: string; kind: "event" | "passage"; state: string }[];
  documents: { ref: string; name: string; state: DocumentState }[]; steps: Step[];
  target: Record<string, unknown>; measured: { target_note: string; price: Record<string, unknown> };
  approval: { state: string | null; review_id: string | null; saved_at: string | null; account: Account | null;
    notes: string | null; masked: boolean | null; differs: string[] };
  reading: ReadingRecordView | null; history: ChainHistory;
  binding: { chain_sha256: string; approval_id: string | null; parent_review_id: string | null;
    parent_reading_id: string | null };
};
export type EventChainsView = {
  view_version: string; provider_called: false; thesis: { id: string; latest_version: number }; chains: ChainView[];
};

// ---------------------------------------------------------------- the reader

class Refused extends Error {}
type Rec = Record<string, unknown>;

function need(ok: unknown, where: string, rule: string): asserts ok {
  if (!ok) throw new Refused(`${where}: ${rule}`);
}
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const isNullText = (value: unknown) => value === null || isText(value);
const isCount = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value >= 1;
const SHA = /^[0-9a-f]{64}$/;

function rec(value: unknown, keys: readonly string[], where: string): Rec {
  need(isRec(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)),
    where, "does not have exactly the expected fields");
  return value;
}
function list(value: unknown, where: string): unknown[] {
  need(Array.isArray(value), where, "is not a list");
  return value;
}

const CHAIN_STATES: readonly ChainState[] = ["unavailable", "needs_revalidation", "evidence_changed", "thesis_newer",
  "available"];
const DOCUMENT_STATES: readonly string[] = ["verified", "changed", "missing", "superseded", "unreadable"];
const ITEM_STATES = ["same", "changed", "gone", "unreadable"];
const JUDGMENTS: readonly string[] = ["supports", "refutes", "neither", "not_sure"];
const ARROW = /→|⟶|->/;
// The server's rules (event_chain_text.FIGURE and STEP), digit for digit: only 0 to 9 make a figure or a step number.
// Both sides are held to one table of texts, tests/fixtures/event-chain-masking.json.
const FIGURE = /[0-9]+(?:[.,][0-9]+)*%?/g;
// "step", "steps", or "שלב"/"שלבים" with up to three of the Hebrew prefix letters, not inside another word (a letter,
// digit or underscore before it, as Python's \w reads one).
const STEP = /(?<![\p{L}\p{N}_])(?:steps?|[והבכלמש]{0,3}(?:שלבים|שלב))\s+([0-9]+)/gdiu;
const NO_PRICE = "Not measured: no monthly or daily price source is retained";

/** The figures of a text outside step references that name a step from 1 to `steps` (the server's masking rule). */
function figuresOutsideSteps(text: string, steps: number): RegExpMatchArray[] {
  const spans: [number, number][] = [];
  for (const found of text.matchAll(STEP)) {
    const span = (found as RegExpMatchArray & { indices: [number, number][] }).indices[1];
    if (Number(found[1]) >= 1 && Number(found[1]) <= steps) spans.push(span);
  }
  return [...text.matchAll(FIGURE)].filter((m) => !spans.some(([from, to]) =>
    from <= m.index! && m.index! + m[0].length <= to));
}

/** The text with every figure outside step references replaced by "[figure withheld]". */
export function maskedText(text: string, steps: number): string {
  let out = "";
  let last = 0;
  for (const found of figuresOutsideSteps(text, steps)) {
    out += text.slice(last, found.index!) + FIGURE_WITHHELD;
    last = found.index! + found[0].length;
  }
  return out + text.slice(last);
}

/** Assistant text and served problems or reasons: never an arrow (the owner's words and quotes are not checked). */
function noArrow(value: unknown, where: string): void {
  need(typeof value !== "string" || !ARROW.test(value), where, "holds an arrow character");
}
const noArrows = (values: unknown, where: string): void => {
  if (Array.isArray(values)) values.forEach((value, at) => noArrow(value, `${where}[${at}]`));
};

function account(value: unknown, where: string): void {
  const found = rec(value, ["user_id", "username"], where);
  need(isText(found.user_id) && isText(found.username), where, "is not an account");
}

function basisOf(value: unknown, where: string, chain: ChainView): Basis {
  const found = rec(value, ["chain", "evidence_sha256", "thesis"], where);
  const link = rec(found.chain, ["id", "sha256", "version"], `${where}.chain`);
  need(link.id === chain.id && typeof link.sha256 === "string" && SHA.test(link.sha256) && isCount(link.version),
    `${where}.chain`, "does not name this chain's version");
  need(found.evidence_sha256 === null || (typeof found.evidence_sha256 === "string" && SHA.test(found.evidence_sha256)),
    `${where}.evidence_sha256`, "is not a SHA-256");
  const thesis = rec(found.thesis, ["id", "sha256", "version"], `${where}.thesis`);
  need(thesis.id === "copper" && typeof thesis.sha256 === "string" && SHA.test(thesis.sha256) && isCount(thesis.version),
    `${where}.thesis`, "is not a copper thesis version");
  return found as unknown as Basis;
}

/** One owner record as served: its fields, its state, and the masking its basis documents require (by the step count
 * of the version the record names, as the server masks it). */
function recordOf(value: unknown, kind: "reviews" | "readings", index: number, chain: ChainView, versions: Rec[],
                  where: string, previous: string | null): void {
  const review = kind === "reviews";
  const text = review ? "notes" : "line";
  const id = review ? "review_id" : "reading_id";
  const parent = review ? "parent_review_id" : "parent_reading_id";
  const keys = review ? ["review_id", "parent_review_id", "sequence", "status", "notes", "account", "saved_at"]
    : ["reading_id", "parent_reading_id", "sequence", "approval_id", "target", "short_term", "long_term", "line",
      "account", "saved_at"];
  const found = rec(value, [...keys, "basis", "basis_documents", "masked", "mask_reason", "state", "differs"], where);
  need(typeof found[id] === "string" && SHA.test(found[id] as string), `${where}.${id}`, "is not a content id");
  need(found[parent] === previous, `${where}.${parent}`, "is not the record before it");
  need(found.sequence === index + 1, `${where}.sequence`, "is not its position in the history");
  need(typeof found.saved_at === "string" && typeof found[text] === "string", where, "does not hold its text");
  account(found.account, `${where}.account`);
  const basis = basisOf(found.basis, `${where}.basis`, chain);
  const version = versions[basis.chain.version - 1];
  need(version !== undefined, `${where}.basis.chain`, "names a version that is not in the history");
  if (review) {
    need(found.status === "approved" || found.status === "needs_revision", `${where}.status`, "is not a review status");
    need(["needs_revision", "approved", "approved_earlier_basis"].includes(found.state as string),
      `${where}.state`, "is not a review state");
    need((found.status === "needs_revision") === (found.state === "needs_revision"), `${where}.state`,
      "does not follow from the status");
  } else {
    need(typeof found.approval_id === "string" && SHA.test(found.approval_id), `${where}.approval_id`,
      "is not a review id");
    need(JUDGMENTS.includes(found.short_term as string) && JUDGMENTS.includes(found.long_term as string),
      `${where}.judgments`, "is not a judgment");
    const target = rec(found.target, ["id", "kind"], `${where}.target`);
    need(isText(target.id) && isText(target.kind), `${where}.target`, "is not a target");
    need(found.state === "current" || found.state === "earlier_basis", `${where}.state`, "is not a reading state");
  }
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
  if (failing) {
    need(figuresOutsideSteps(found[text] as string, version.steps as number).length === 0, `${where}.${text}`,
      "still holds a figure outside step references while a basis document fails");
  }
  need(Array.isArray(found.differs) && found.differs.every(isText), `${where}.differs`, "is not a list of reasons");
  noArrows(found.differs, `${where}.differs`);
}

function stepOf(value: unknown, where: string, chain: ChainView): void {
  need(isRec(value), where, "is not a step");
  if (value.kind === "not_stated") {
    rec(value, ["kind", "text"], where);
    need(isText(value.text), `${where}.text`, "is empty");
    noArrow(value.text, `${where}.text`);
    return;
  }
  if (value.kind === "mechanism") {
    rec(value, ["kind", "id", "text"], where);
    need(isText(value.id) && isText(value.text), where, "is empty");
    noArrow(value.text, `${where}.text`);
    return;
  }
  need(value.kind === "stated", `${where}.kind`, "is not a step kind");
  rec(value, ["kind", "label", "ref", "quote", "pinned_quote", "current_quote", "where", "pinned_where",
    "current_where", "document", "state", "problem"], where);
  need(isText(value.ref) && isText(value.where) && isText(value.state), where, "does not name its passage");
  need(isNullText(value.label) && isNullText(value.quote) && isNullText(value.pinned_quote)
    && isNullText(value.current_quote) && isNullText(value.pinned_where) && isNullText(value.current_where)
    && isNullText(value.problem), where, "holds a field that is not text");
  noArrow(value.label, `${where}.label`);
  noArrow(value.problem, `${where}.problem`);
  const document = rec(value.document, ["ref", "name", "state"], `${where}.document`);
  need(isText(document.ref) && isText(document.name) && DOCUMENT_STATES.includes(document.state as string),
    `${where}.document`, "is not a document state");
  const listed = chain.documents.find((item) => item.ref === document.ref);
  need(listed !== undefined && listed.state === document.state, `${where}.document`,
    "does not match the chain's document list");
  const quotes = [value.quote, value.pinned_quote, value.current_quote];
  const item = chain.items.find((one) => one.kind === "passage" && one.ref === value.ref);
  need(item !== undefined, where, "names a passage that is not among the chain's items");
  if (document.state !== "verified") {
    need(value.state === document.state, `${where}.state`, "does not follow from its document");
    need(quotes.every((quote) => quote === null), where, "carries a quote while its document does not verify");
    need(isText(value.problem), `${where}.problem`, "does not say why the quote is withheld");
  } else if (value.state === "verified") {
    need(isText(value.quote) && value.pinned_quote === null && value.current_quote === null && item.state !== "changed"
      && item.state !== "gone", `${where}.quote`, "is not the verified quote of an unchanged item");
  } else if (value.state === "not_found") {
    need(quotes.every((quote) => quote === null) && isText(value.problem), where, "carries a quote that is not found");
  } else if (value.state === "record_changed") {
    need(item.state === "changed", `${where}.state`, "is changed while its item is not");
    need(value.quote === null, `${where}.quote`, "carries a quote beside a changed record's two wordings");
    need(isText(value.pinned_quote) && isText(value.pinned_where) && isText(value.current_where),
      `${where}.pinned_quote`, "does not hold the pinned wording of a changed record");
    // The current wording is withheld only when the record's document itself differs from the pinned one.
    need(isText(value.current_quote) || /: its document\b/.test(String(value.problem)), `${where}.current_quote`,
      "does not hold the current wording beside the pinned wording");
  } else if (value.state === "record_gone") {
    need(item.state === "gone" && value.quote === null && value.current_quote === null && isText(value.pinned_where),
      `${where}.state`, "is not a gone record");
  } else {
    need(false, `${where}.state`, "is not a step state");
  }
  const shown = ["verified", "record_changed", "record_gone"].includes(value.state);
  need(shown ? isText(value.label) : value.label === null || !/\d/.test(value.label as string), `${where}.label`,
    "is shown with a withheld source although it holds a digit, or withheld with a source that verifies");
}

/** Severity of the state the items and documents alone give, in the server's rule order. */
function derivedState(chain: ChainView): ChainState {
  if (chain.documents.some((item) => item.state === "missing" || item.state === "unreadable")) return "unavailable";
  if (chain.documents.some((item) => item.state !== "verified")
    || chain.steps.some((step) => step.kind === "stated" && step.state === "not_found")) return "needs_revalidation";
  if (chain.items.some((item) => item.state === "changed" || item.state === "gone")) return "evidence_changed";
  return "available";
}

function chainOf(value: unknown, where: string): ChainView {
  const found = rec(value, ["id", "title", "latest_version", "published_on", "state", "reasons", "event", "items",
    "documents", "steps", "target", "measured", "approval", "reading", "history", "binding"], where);
  const chain = found as unknown as ChainView;
  need(isText(found.id) && isText(found.title) && isText(found.published_on) && isCount(found.latest_version),
    where, "does not name its chain");
  where = `chains[${found.id}]`;
  noArrow(found.title, `${where}.title`);
  need(CHAIN_STATES.includes(found.state as ChainState), `${where}.state`, "is not a chain state");
  need(Array.isArray(found.reasons) && found.reasons.every(isText) && (found.reasons.length === 0) === (found.state === "available"),
    `${where}.reasons`, "does not match the chain's state");
  noArrows(found.reasons, `${where}.reasons`);
  const event = rec(found.event, ["passage", "state", "pinned", "current"], `${where}.event`);
  need(isText(event.passage) && ITEM_STATES.includes(event.state as string), `${where}.event`, "is not an event state");
  const items = list(found.items, `${where}.items`);
  items.forEach((item, at) => {
    const one = rec(item, ["ref", "kind", "state"], `${where}.items[${at}]`);
    need(isText(one.ref) && (one.kind === "event" || one.kind === "passage") && ITEM_STATES.includes(one.state as string),
      `${where}.items[${at}]`, "is not an item state");
  });
  need(items.length > 0 && (items[0] as Rec).kind === "event" && (items[0] as Rec).state === event.state,
    `${where}.items`, "does not begin with the event");
  const documents = list(found.documents, `${where}.documents`);
  documents.forEach((item, at) => {
    const one = rec(item, ["ref", "name", "state"], `${where}.documents[${at}]`);
    need(isText(one.ref) && isText(one.name) && DOCUMENT_STATES.includes(one.state as string),
      `${where}.documents[${at}]`, "is not a document state");
  });
  const steps = list(found.steps, `${where}.steps`);
  need(steps.length > 0, `${where}.steps`, "is empty");
  steps.forEach((step, at) => stepOf(step, `${where}.steps[${at}]`, chain));
  const derived = derivedState(chain);
  const served = CHAIN_STATES.indexOf(chain.state);
  need(served <= CHAIN_STATES.indexOf(derived), `${where}.state`,
    "is less severe than its items and documents give");
  const target = rec(found.target, ["kind", "id", "title", "statement", "status", "change_pct", "measure", "state"],
    `${where}.target`);
  need(isText(target.kind) && isText(target.id) && isText(target.state), `${where}.target`, "does not name its target");
  const measured = rec(found.measured, ["target_note", "price"], `${where}.measured`);
  need(measured.target_note === `The thesis's own measure of this ${target.kind}. It does not measure this event.`,
    `${where}.measured.target_note`, "is not the fixed note");
  noArrow(measured.target_note, `${where}.measured.target_note`);
  const price = measured.price;
  need(isRec(price) && price.short_term === NO_PRICE, `${where}.measured.price.short_term`, "is not the fixed note");
  noArrow(price.problem, `${where}.measured.price.problem`);
  if (price.state === "not_yet_measured") {
    need(price.text === `Not yet measured: the retained series ends at ${price.last_year}`
      + (price.last_estimated === true ? " (estimate)" : ""), `${where}.measured.price.text`,
    "is not the fixed note for a year without a later price");
  }
  historyOf(found.history, `${where}.history`, chain);
  ownerOf(chain, where);
  return chain;
}

function historyOf(value: unknown, where: string, chain: ChainView): void {
  const found = rec(value, ["state", "problem", "versions", "reviews", "readings"], where);
  need(found.state === "valid" || found.state === "invalid", `${where}.state`, "is not a history state");
  need((found.state === "invalid") === isText(found.problem) && (found.problem === null || isText(found.problem)),
    `${where}.problem`, "does not follow from the history's state");
  noArrow(found.problem, `${where}.problem`);
  const versions = list(found.versions, `${where}.versions`) as Rec[];
  need(versions.length === chain.latest_version, `${where}.versions`, "does not hold each version once");
  versions.forEach((item, at) => {
    const one = rec(item, ["version", "sha256", "published_on", "title", "target", "thesis", "change", "passages",
      "basis_documents", "steps", "state"], `${where}.versions[${at}]`);
    need(one.version === at + 1 && typeof one.sha256 === "string" && SHA.test(one.sha256)
      && one.state === (at === versions.length - 1 ? "latest" : "earlier"), `${where}.versions[${at}]`,
    "is out of order");
    need(isCount(one.steps) && (at < versions.length - 1 || one.steps === chain.steps.length),
      `${where}.versions[${at}].steps`, "is not the version's step count");
    noArrow(one.title, `${where}.versions[${at}].title`);
    if (isRec(one.change)) {
      noArrow(one.change.note, `${where}.versions[${at}].change.note`);
      noArrow(one.change.review_note, `${where}.versions[${at}].change.review_note`);
    }
    for (const [number, passage] of list(one.passages, `${where}.versions[${at}].passages`).entries()) {
      const place = `${where}.versions[${at}].passages[${number}]`;
      const shown = rec(passage, ["ref", "where", "document", "quote", "state"], place);
      const document = rec(shown.document, ["ref", "name", "state"], `${place}.document`);
      need(isText(shown.ref) && isText(shown.where) && isText(document.ref) && isText(shown.state)
        && typeof document.state === "string", place, "is not a passage");
      need(shown.quote === null ? shown.state !== "verified" : (shown.state === "verified" && isText(shown.quote)),
        `${place}.quote`, "is shown while its document does not verify");
    }
  });
  need((versions[versions.length - 1] as Rec).sha256 === chain.binding.chain_sha256, `${where}.versions`,
    "does not end with the version the binding names");
  const reviews = list(found.reviews, `${where}.reviews`);
  const readings = list(found.readings, `${where}.readings`);
  need(found.state === "valid" || (reviews.length === 0 && readings.length === 0), `${where}.reviews`,
    "holds records in a history that cannot be verified");
  let previous: string | null = null;
  reviews.forEach((item, at) => {
    recordOf(item, "reviews", at, chain, versions, `${where}.reviews[${at}]`, previous);
    previous = (item as Rec).review_id as string;
  });
  previous = null;
  readings.forEach((item, at) => {
    recordOf(item, "readings", at, chain, versions, `${where}.readings[${at}]`, previous);
    previous = (item as Rec).reading_id as string;
  });
  chain.history = found as unknown as ChainHistory;
}

/** The approval, current reading and binding: each must follow from the history and the chain's state. */
function ownerOf(chain: ChainView, where: string): void {
  const history = chain.history;
  const approval = rec(chain.approval, ["state", "review_id", "saved_at", "account", "notes", "masked", "differs"],
    `${where}.approval`);
  const binding = rec(chain.binding, ["chain_sha256", "approval_id", "parent_review_id", "parent_reading_id"],
    `${where}.binding`);
  const lastReview = history.reviews[history.reviews.length - 1];
  const lastReading = history.readings[history.readings.length - 1];
  need(typeof binding.chain_sha256 === "string" && SHA.test(binding.chain_sha256), `${where}.binding`,
    "does not name a chain version");
  need(binding.parent_review_id === (lastReview?.review_id ?? null)
    && binding.parent_reading_id === (lastReading?.reading_id ?? null), `${where}.binding`,
  "does not name the latest saved records");
  need(Array.isArray(approval.differs) && approval.differs.every(isText), `${where}.approval.differs`, "is not a list");
  noArrows(approval.differs, `${where}.approval.differs`);
  if (history.state === "invalid") {
    need(approval.state === null && approval.review_id === null && approval.saved_at === null
      && approval.account === null && approval.notes === null && approval.masked === null,
    `${where}.approval`, "holds a state although the history cannot be verified");
    need(binding.approval_id === null && chain.reading === null, `${where}.binding`,
      "names an approval although the history cannot be verified");
    return;
  }
  const onThis = lastReview !== undefined && lastReview.basis.chain.sha256 === binding.chain_sha256;
  if (!onThis) {
    need(approval.state === "awaiting_review" && approval.review_id === null && approval.saved_at === null
      && approval.account === null && approval.notes === null && approval.masked === false, `${where}.approval`,
    "is not awaiting review although no review is on this version");
  } else {
    need(approval.state === lastReview.state && approval.review_id === lastReview.review_id
      && approval.saved_at === lastReview.saved_at && approval.notes === lastReview.notes
      && approval.masked === lastReview.masked && isRec(approval.account), `${where}.approval`,
    "is not the latest review on this version");
  }
  const approved = approval.state === "approved";
  if (approved) {
    need(chain.state === "available", `${where}.approval`, "is shown as current on a chain that is not available");
    need(history.reviews.filter((item) => item.state === "approved").length === 1, `${where}.approval`,
      "is not the only current approval");
  } else {
    need(history.reviews.every((item) => item.state !== "approved"), `${where}.history.reviews`,
      "holds a current approval that the chain does not show");
  }
  need(binding.approval_id === (approved ? approval.review_id : null), `${where}.binding.approval_id`,
    "does not follow from the approval");
  const current = chain.reading;
  need(history.readings.every((item, at) => (item.state === "current") === (at === history.readings.length - 1
    && approved && item.approval_id === binding.approval_id && item.basis.chain.sha256 === binding.chain_sha256)),
  `${where}.history.readings`, "marks a reading current that is not the latest on the current approval");
  need(current === null ? lastReading?.state !== "current" : (lastReading !== undefined
    && JSON.stringify(current) === JSON.stringify(lastReading) && current.state === "current"),
  `${where}.reading`, "is not the latest reading while it is current");
}

/** Why a served reply cannot be read, naming the place and rule (never a value), or null when it can. */
export function eventChainsRefusal(body: unknown): string | null {
  try {
    const found = rec(body, ["view_version", "provider_called", "thesis", "chains"], "reply");
    need(found.view_version === EVENT_CHAIN_VIEW_VERSION, "view_version", "is not the version this page reads");
    need(found.provider_called === false, "provider_called", "is not false");
    const thesis = rec(found.thesis, ["id", "latest_version"], "thesis");
    need(thesis.id === "copper" && isCount(thesis.latest_version), "thesis", "is not the copper thesis");
    const chains = list(found.chains, "chains").map((item, at) => chainOf(item, `chains[${at}]`));
    need(new Set(chains.map((item) => item.id)).size === chains.length, "chains", "repeats a chain");
    return null;
  } catch (error) {
    if (error instanceof Refused) return error.message;
    if (error instanceof TypeError || error instanceof RangeError) return "reply: is not shaped as expected";
    throw error;
  }
}

export async function fetchEventChains(signal?: AbortSignal): Promise<Loaded<EventChainsView>> {
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
  const refusal = eventChainsRefusal(body);
  return refusal === null ? { state: "ready", data: body as EventChainsView }
    : { state: "error", message: `The reply could not be read by this page (${refusal}).` };
}

// ---------------------------------------------------------------- the saves

export type ReviewBody = { parent_review_id: string | null; chain_sha256: string; status: "approved" | "needs_revision";
  notes: string };
export type ReadingBody = { parent_reading_id: string | null; chain_sha256: string; approval_id: string;
  short_term: Judgment; long_term: Judgment; line: string };
export type SentSave = { kind: "reviews"; body: ReviewBody } | { kind: "readings"; body: ReadingBody };
export type SavedRecord = { record_version: string; chain_id: string; sequence: number; basis: Rec; account: Account;
  saved_at: string } & Rec;
export type RecordReply = { record: SavedRecord };
export type Action<T> =
  | { state: "ready"; status: number; data: T }
  | { state: "blocked"; message: string; latest: string | null }
  | { state: "failed" | "unconfirmed"; message: string };

/** The exact body of a review save (the owner's text is trimmed as the server stores it). */
export const reviewBody = (chain: ChainView, status: ReviewBody["status"], notes: string): ReviewBody =>
  ({ parent_review_id: chain.binding.parent_review_id, chain_sha256: chain.binding.chain_sha256, status,
     notes: notes.trim() });

/** The exact body of a reading save, or null while the chain has no current approval to bind it to. */
export const readingBody = (chain: ChainView, shortTerm: Judgment, longTerm: Judgment, line: string):
  ReadingBody | null => chain.binding.approval_id === null ? null
  : { parent_reading_id: chain.binding.parent_reading_id, chain_sha256: chain.binding.chain_sha256,
      approval_id: chain.binding.approval_id, short_term: shortTerm, long_term: longTerm, line: line.trim() };

async function post(path: string, body: object): Promise<{ status: number; body: unknown } | Action<never>> {
  let response: Response;
  try {
    response = await fetch(path, { method: "POST", body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", Accept: "application/json", [EVENT_CHAIN_HEADER]: "1",
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
  return { status: response.status, body: payload };
}

const UNREADABLE = "The reply could not be read as the record that was sent; check the saved history before trying again.";

/** Whether a record the server returned is the one that was sent. */
function isSentRecord(record: unknown, chain: ChainView, sent: SentSave): record is SavedRecord {
  if (!isRec(record) || !isRec(record.basis) || !isRec(record.basis.chain)) return false;
  const body = sent.body;
  const same = record.chain_id === chain.id && record.basis.chain.sha256 === body.chain_sha256
    && record.basis.chain.id === chain.id && typeof record.sequence === "number" && isRec(record.account);
  if (!same) return false;
  if (sent.kind === "reviews") {
    return record.parent_review_id === sent.body.parent_review_id && record.status === sent.body.status
      && record.notes === sent.body.notes;
  }
  const reading = sent.body;
  return record.parent_reading_id === reading.parent_reading_id && record.approval_id === reading.approval_id
    && record.short_term === reading.short_term && record.long_term === reading.long_term
    && record.line === reading.line;
}

async function save(chain: ChainView, sent: SentSave): Promise<Action<RecordReply>> {
  const reply = await post(`${BASE}/${encodeURIComponent(chain.id)}/${sent.kind}`, sent.body);
  if ("state" in reply) return reply;
  if (reply.status !== 201 || !isRec(reply.body) || Object.keys(reply.body).length !== 1
    || !isSentRecord(reply.body.record, chain, sent)) return { state: "unconfirmed", message: UNREADABLE };
  return { state: "ready", status: 201, data: reply.body as RecordReply };
}

export async function saveReview(chain: ChainView, status: ReviewBody["status"], notes: string):
  Promise<Action<RecordReply>> {
  return save(chain, { kind: "reviews", body: reviewBody(chain, status, notes) });
}

export async function saveReading(chain: ChainView, shortTerm: Judgment, longTerm: Judgment, line: string):
  Promise<Action<RecordReply>> {
  const body = readingBody(chain, shortTerm, longTerm, line);
  if (body === null) return { state: "failed", message: "The chain has no current approval to bind a reading to." };
  return save(chain, { kind: "readings", body });
}

// ---------------------------------------------------------------- settling a lost reply

/** Unmasked saved text equals the sent text; masked saved text matches it with each marker standing for one figure. */
function sameText(record: { masked: boolean }, saved: string, sent: string): boolean {
  if (saved === sent) return true;
  if (!record.masked || !saved.includes(FIGURE_WITHHELD)) return false;
  const parts = saved.split(FIGURE_WITHHELD).map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp(`^${parts.join(FIGURE.source)}$`, "s").test(sent);
}

/**
 * What the saved history says about a save whose reply was lost. Only the record that follows the sent parent can be
 * it, and it is it only if its content and the chain version it is bound to (and a reading's approval) are what was
 * sent: the parent alone never identifies a save. "saved": it is the latest. "superseded": newer records follow.
 * "conflict": a record took that place with other content or another binding. "not-saved": none follows the parent.
 * "unverifiable": the history cannot be verified, so nothing is concluded and the save must not be sent again.
 * Read-only: this never sends the save again.
 */
export function settle(history: ChainHistory, sent: SentSave): "saved" | "superseded" | "conflict" | "not-saved" | "unverifiable" {
  if (history.state === "invalid") return "unverifiable";
  const records: (ReviewRecordView | ReadingRecordView)[] = sent.kind === "reviews" ? history.reviews : history.readings;
  const at = records.findIndex((item) => sent.kind === "reviews"
    ? (item as ReviewRecordView).parent_review_id === sent.body.parent_review_id
    : (item as ReadingRecordView).parent_reading_id === sent.body.parent_reading_id);
  if (at < 0) return "not-saved";
  const found = records[at];
  let same = found.basis.chain.sha256 === sent.body.chain_sha256;
  if (sent.kind === "reviews") {
    const review = found as ReviewRecordView;
    same = same && review.status === sent.body.status && sameText(review, review.notes, sent.body.notes);
  } else {
    const reading = found as ReadingRecordView;
    same = same && reading.approval_id === sent.body.approval_id && reading.short_term === sent.body.short_term
      && reading.long_term === sent.body.long_term && sameText(reading, reading.line, sent.body.line);
  }
  if (!same) return "conflict";
  return at === records.length - 1 ? "saved" : "superseded";
}
