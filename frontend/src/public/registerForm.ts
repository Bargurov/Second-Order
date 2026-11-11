// The registration form as a pure state machine. The form checks each field by the server's rules before sending, sends
// exactly the contract's four fields on the person's submit, and handles every reply: a received registration drops
// everything typed; a refusal, or an unconfirmed reply that proves nothing, keeps what was typed except both password
// fields, which are cleared. After an unconfirmed reply the person may check by signing in, or register again by
// typing the password again (the server answers the same username and password as a duplicate). Nothing here sends,
// retries or stores anything, and no password is kept to be replayed: it lives only in this state while it is typed.
import {
  REGISTRATION_RULES, type OnboardingError, type OnboardingErrorCode, type RegistrationForm, type RegistrationReply,
} from "../contracts/onboarding.ts";
import type { RegistrationStatus, Reply } from "../contracts/user.ts";

/** What the person types: the contract's four fields and the password typed a second time, which is never sent. */
export interface RegisterDraft extends RegistrationForm { repeat: string }
export type DraftField = keyof RegisterDraft;
export type Phase = "editing" | "sending" | "received";

export interface RegisterNotice { tone: "refused" | "unconfirmed"; title: string; detail: string }

export interface RegisterState {
  draft: RegisterDraft;
  phase: Phase;
  errors: Partial<Record<DraftField, string>>;
  notice: RegisterNotice | null;
  received: { registration: RegistrationStatus; duplicate: boolean } | null;
  /** The last reply proved nothing: the page offers a check by signing in until the person submits again. */
  unconfirmed: boolean;
}

export type RegisterEvent =
  | { type: "edit"; field: DraftField; value: string }
  /** The person's Register button. */
  | { type: "submit" }
  | { type: "reply"; reply: Reply<RegistrationReply, OnboardingError> };

const EMPTY_DRAFT: RegisterDraft = { username: "", display_name: "", password: "", repeat: "", note: "" };
export const emptyRegister: RegisterState = { draft: EMPTY_DRAFT, phase: "editing", errors: {}, notice: null,
                                              received: null, unconfirmed: false };

const CONTROL = /[\x00-\x1f\x7f]/;

/** Each field's problem by the server's rules (src/contracts/onboarding.ts), or none. The server checks again. */
export function draftProblems(draft: RegisterDraft): Partial<Record<DraftField, string>> {
  const problems: Partial<Record<DraftField, string>> = {};
  if (!REGISTRATION_RULES.username.test(draft.username)) {
    problems.username = "Use 3 to 40 lowercase letters, digits, dots, hyphens or underscores, starting with a letter " +
      "or digit.";
  }
  if (!draft.display_name.trim() || draft.display_name.length > REGISTRATION_RULES.maxDisplayName ||
      CONTROL.test(draft.display_name)) {
    problems.display_name = `Give a display name of 1 to ${REGISTRATION_RULES.maxDisplayName} characters.`;
  }
  if (draft.password.length < REGISTRATION_RULES.minPassword || draft.password.length > REGISTRATION_RULES.maxPassword ||
      CONTROL.test(draft.password)) {
    problems.password = `Use ${REGISTRATION_RULES.minPassword} to ${REGISTRATION_RULES.maxPassword} characters, ` +
      "without control characters.";
  } else if (draft.repeat !== draft.password) {
    problems.repeat = "The two passwords differ.";
  }
  if (draft.note.length > REGISTRATION_RULES.maxNote || CONTROL.test(draft.note)) {
    problems.note = `Keep the note to ${REGISTRATION_RULES.maxNote} characters in one paragraph.`;
  }
  return problems;
}

const TITLE: Partial<Record<OnboardingErrorCode, string>> = {
  invalid_request: "The form was refused as malformed",
  payload_too_large: "The form is too large to send",
  forbidden: "This page's registration was not accepted",
  accounts_unavailable: "This server does not take registrations",
};

const withoutPassword = (draft: RegisterDraft): RegisterDraft => ({ ...draft, password: "", repeat: "" });

function replied(state: RegisterState, reply: Reply<RegistrationReply, OnboardingError>): RegisterState {
  if (reply.state === "ok") {
    return { ...emptyRegister, phase: "received",
             received: { registration: reply.data.registration, duplicate: reply.data.duplicate } };
  }
  if (reply.state === "unconfirmed") {
    return { ...state, phase: "editing", draft: withoutPassword(state.draft), errors: {}, unconfirmed: true,
      notice: { tone: "unconfirmed", title: "No confirmed reply",
        detail: "This page could not confirm that your registration was received, and it keeps no password. Check " +
          "by signing in with the username and password you chose: a registration that was received shows its " +
          "status. Or type the password again and register: if the first one was received, the server recognises " +
          "the same username and password as a repeat and records nothing new." } };
  }
  const error = reply.error;
  const field = error.code === "invalid_registration" ? error.field
    : error.code === "username_unavailable" ? "username" : undefined;
  const notice: RegisterNotice = field
    ? { tone: "refused", title: "Not registered",
        detail: "Nothing was recorded. Correct the marked field, type the password again and register." }
    : { tone: "refused", title: TITLE[error.code] ?? "The registration was refused",
        detail: `${error.detail} Nothing was recorded.` };
  return { ...state, phase: "editing", draft: withoutPassword(state.draft), notice,
           errors: field ? { [field]: error.detail } : {} };
}

export function reduceRegister(state: RegisterState, event: RegisterEvent): RegisterState {
  switch (event.type) {
    case "edit": {
      if (state.phase !== "editing") return state;  // Read-only while sending.
      // A note is one paragraph: line breaks and tabs, typed or pasted, become spaces.
      const value = event.field === "note" ? event.value.replace(/[\r\n\t]+/g, " ") : event.value;
      const errors = { ...state.errors };  // Editing a field clears its own mark (and the repeat's, for the password).
      delete errors[event.field];
      if (event.field === "password") delete errors.repeat;
      return { ...state, draft: { ...state.draft, [event.field]: value }, errors };
    }
    case "submit": {
      if (state.phase !== "editing") return state;
      const errors = draftProblems(state.draft);
      return Object.keys(errors).length > 0 ? { ...state, errors }
        : { ...state, phase: "sending", errors: {}, notice: null, unconfirmed: false };
    }
    case "reply":
      return state.phase === "sending" ? replied(state, event.reply) : state;
  }
}

/** The one body to send now, or null: exactly the contract's four fields, never the repeated password. */
export function toSend(state: RegisterState): RegistrationForm | null {
  if (state.phase !== "sending") return null;
  const { username, display_name, password, note } = state.draft;
  return { username, display_name, password, note };
}
