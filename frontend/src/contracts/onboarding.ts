// The onboarding contract (onboarding-api-0.1, docs/onboarding-contract.md): the public credit terms and the
// registration the signed-out pages read and send, and the props the shell gives those pages. Owned by the logic
// conversation; the public pages import it and never edit it.
//
// Readers are fail-closed like the user contract's: a payload missing a required field, carrying an unknown state or
// contradicting itself is refused as unreadable. Nothing here carries money, a currency, a model or provider name, a
// token count or a planning estimate: credit terms are points, Effort and source size only. The request helpers only
// describe requests; nothing is sent until a caller invokes one, and none retries. A password goes only into the one
// registration or sign-in request the person submits; nothing here keeps it.
import {
  ADMIN_ONLY_KEYS, EFFORTS, SESSION_HEADER, oneOf, record, registrationProblem, request, text,
  type Effort, type EffortOption, type Fetcher, type Read, type RegistrationStatus, type Reply, type Session,
  type SignedOutReason,
} from "./user.ts";

export type { RegistrationStatus } from "./user.ts";

export const ONBOARDING_CONTRACT = "onboarding-api-0.1";
export const CREDIT_TERMS_STATES = ["configured", "no_credit_policy", "no_effort_enabled"] as const;
export const EXAMPLES = ["short", "medium", "long"] as const;
export const ONBOARDING_ERROR_CODES = ["username_unavailable", "invalid_registration", "invalid_request",
  "payload_too_large", "forbidden", "accounts_unavailable", "internal_error"] as const;
/** The server's rules for a registration, for checking a form before it is sent; the server checks them again. */
export const REGISTRATION_RULES = {
  username: /^[a-z0-9][a-z0-9._-]{2,39}$/, minPassword: 10, maxPassword: 256, maxDisplayName: 80, maxNote: 500,
} as const;
/** The signed-out pages' own addresses (docs/onboarding-contract.md section 7). Any other path shows sign-in. */
export const PUBLIC_PATHS = { landing: "/", register: "/register", signIn: "/sign-in", credits: "/credits" } as const;
/** The fields a refused registration can name (`field` on invalid_registration). */
export const REGISTRATION_FIELDS = ["username", "display_name", "password", "note"] as const;

export type CreditTermsState = (typeof CREDIT_TERMS_STATES)[number];
export type ExampleSize = (typeof EXAMPLES)[number];
export type OnboardingErrorCode = (typeof ONBOARDING_ERROR_CODES)[number];
export type RegistrationField = (typeof REGISTRATION_FIELDS)[number];

export interface ExampleQuote { effort: Effort; credits: number }
export interface CreditExample { example: ExampleSize; label: string; characters: number; quotes: ExampleQuote[] }
export interface CreditTerms {
  contract: typeof ONBOARDING_CONTRACT; state: CreditTermsState; detail: string | null; policy_version: string | null;
  efforts: EffortOption[]; effort_note: string; size_note: string | null;
  /** How long a quote stays valid under the active policy (null when none is configured). */
  quote_valid_seconds: number | null; examples: CreditExample[]; rules: string[];
}
export interface RegistrationForm { username: string; display_name: string; password: string; note: string }
export interface RegistrationReply {
  contract: typeof ONBOARDING_CONTRACT; duplicate: boolean; registration: RegistrationStatus;
}
export interface OnboardingError {
  contract: typeof ONBOARDING_CONTRACT; code: OnboardingErrorCode; detail: string;
  /** On invalid_registration: the field whose rule was not met. */
  field?: RegistrationField;
}

/** What the shell gives the signed-out pages of the Client build (src/public/PublicApp.tsx). */
export interface PublicAppProps {
  /** Why nobody is signed in. */
  reason: SignedOutReason;
  /** Hand the session a sign-in returned to the shell, which mounts the role's app (or reloads into its build). */
  onSignedIn: (session: Session) => void;
}

const count = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;

function leaked(value: unknown, depth = 0): string | null {
  if (depth > 8 || typeof value !== "object" || value === null) return null;
  for (const [key, item] of Object.entries(value)) {
    if ((ADMIN_ONLY_KEYS as readonly string[]).includes(key)) return key;
    const nested = leaked(item, depth + 1);
    if (nested) return nested;
  }
  return null;
}

function contractProblem(body: unknown): string | null {
  if (!record(body)) return "The reply is not a JSON object.";
  if (body.contract !== ONBOARDING_CONTRACT) return `The reply is not in the ${ONBOARDING_CONTRACT} contract.`;
  const key = leaked(body);
  return key ? `The reply carries an administrator-only field (${key}); it is not shown.` : null;
}

function examplesProblem(examples: unknown, efforts: EffortOption[]): string | null {
  if (!Array.isArray(examples) || examples.length !== EXAMPLES.length) return "The credit examples are not readable.";
  const offered = efforts.map((option) => option.effort);
  for (const [position, example] of examples.entries()) {
    if (!record(example) || example.example !== EXAMPLES[position] || !text(example.label) ||
        !count(example.characters) || !Array.isArray(example.quotes)) return "A credit example is not readable.";
    const quotes = example.quotes as unknown[];
    if (quotes.length !== offered.length || !quotes.every((quote, index) => record(quote) &&
        quote.effort === offered[index] && Number.isInteger(quote.credits) && (quote.credits as number) >= 1)) {
      return "A credit example does not quote every offered Effort in order.";
    }
  }
  const sizes = (examples as CreditExample[]).map((example) => example.characters);
  return sizes.every((size, index) => index === 0 || size > sizes[index - 1]) ? null
    : "The credit examples are not in order of size.";
}

export function readCreditTerms(body: unknown): Read<CreditTerms> {
  const problem = contractProblem(body);
  if (problem) return { ok: false, problem };
  const terms = body as Record<string, unknown>;
  if (!oneOf(CREDIT_TERMS_STATES, terms.state) || !text(terms.effort_note) || !Array.isArray(terms.rules) ||
      terms.rules.length === 0 || !terms.rules.every(text)) return { ok: false, problem: "The credit terms are not readable." };
  if (terms.state !== "configured") {
    const empty = terms.policy_version === null && Array.isArray(terms.efforts) && terms.efforts.length === 0 &&
      Array.isArray(terms.examples) && terms.examples.length === 0 && terms.size_note === null &&
      terms.quote_valid_seconds === null && text(terms.detail);
    return empty ? { ok: true, value: terms as unknown as CreditTerms }
      : { ok: false, problem: "Credit terms that are not configured cannot carry a policy or examples." };
  }
  if (terms.detail !== null || !text(terms.policy_version) || !text(terms.size_note) || !Array.isArray(terms.efforts) ||
      terms.efforts.length === 0 || !count(terms.quote_valid_seconds) || (terms.quote_valid_seconds as number) < 60) {
    return { ok: false, problem: "The configured credit terms are not readable." };
  }
  const efforts = terms.efforts as unknown[];
  const order = efforts.map((option) => record(option) && oneOf(EFFORTS, option.effort) && text(option.label)
    ? EFFORTS.indexOf(option.effort) : -1);
  if (order.some((index, position) => index < 0 || (position > 0 && index <= order[position - 1]))) {
    return { ok: false, problem: "The Effort options are not readable or out of order." };
  }
  const bad = examplesProblem(terms.examples, efforts as EffortOption[]);
  return bad ? { ok: false, problem: bad } : { ok: true, value: terms as unknown as CreditTerms };
}

export function readRegistration(body: unknown): Read<RegistrationReply> {
  const problem = contractProblem(body);
  if (problem) return { ok: false, problem };
  const reply = body as Record<string, unknown>;
  if (typeof reply.duplicate !== "boolean") return { ok: false, problem: "The reply does not say whether it was new." };
  const bad = registrationProblem(reply.registration);
  if (bad) return { ok: false, problem: bad };
  return (reply.registration as RegistrationStatus).status === "pending"
    ? { ok: true, value: reply as unknown as RegistrationReply }
    : { ok: false, problem: "A new registration is pending." };
}

export function readOnboardingError(body: unknown): Read<OnboardingError> {
  const problem = contractProblem(body);
  if (problem) return { ok: false, problem };
  const error = body as Record<string, unknown>;
  if (!oneOf(ONBOARDING_ERROR_CODES, error.code) || !text(error.detail)) {
    return { ok: false, problem: "The refusal is not readable." };
  }
  const named = error.code === "invalid_registration";
  if (named ? !oneOf(REGISTRATION_FIELDS, error.field) : error.field !== undefined) {
    return { ok: false, problem: "The refusal's field is missing or unexpected." };
  }
  return { ok: true, value: error as unknown as OnboardingError };
}

/** A registration form's own problems before sending, or null. The server checks everything again. */
export function registrationFormProblem(form: RegistrationForm): string | null {
  const control = /[\x00-\x1f\x7f]/;
  if (!REGISTRATION_RULES.username.test(form.username)) {
    return "A username is 3 to 40 lowercase letters, digits, dots, hyphens or underscores, starting with a letter or digit.";
  }
  if (!form.display_name.trim() || form.display_name.length > REGISTRATION_RULES.maxDisplayName ||
      control.test(form.display_name)) return `A display name is 1 to ${REGISTRATION_RULES.maxDisplayName} characters.`;
  if (form.password.length < REGISTRATION_RULES.minPassword || form.password.length > REGISTRATION_RULES.maxPassword ||
      control.test(form.password)) {
    return `A password is ${REGISTRATION_RULES.minPassword} to ${REGISTRATION_RULES.maxPassword} characters.`;
  }
  return form.note.length > REGISTRATION_RULES.maxNote || control.test(form.note)
    ? `A note is at most ${REGISTRATION_RULES.maxNote} characters on one line.` : null;
}

/** Request helpers bound to one fetch implementation (the browser's by default; a test transport in tests). */
export function onboardingApi(fetcher: Fetcher = (input, init) => fetch(input, init)) {
  return {
    creditTerms: (): Promise<Reply<CreditTerms, OnboardingError>> =>
      request(fetcher, "GET", "/api/public/credit-terms", undefined, SESSION_HEADER, readCreditTerms,
              readOnboardingError),
    register: (form: RegistrationForm): Promise<Reply<RegistrationReply, OnboardingError>> =>
      request(fetcher, "POST", "/api/public/registrations", { ...form }, SESSION_HEADER, readRegistration,
              readOnboardingError),
  };
}

export type OnboardingApi = ReturnType<typeof onboardingApi>;
