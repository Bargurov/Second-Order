// What a sign-in reply means for the sign-in form (src/shell/SignIn.tsx). A registrant whose registration is pending
// or was not approved gets their own registration back in the refusal (docs/onboarding-contract.md section 4): there
// is no session for them. An unconfirmed reply proves nothing; the password is never sent again on its own.
import type { RegistrationStatus, Reply, Session, SignedInSession } from "../contracts/user.ts";

export type SignInOutcome =
  | { kind: "signed-in"; session: SignedInSession }
  | { kind: "registration"; registration: RegistrationStatus }
  | { kind: "refused"; detail: string }
  | { kind: "unconfirmed"; detail: string };

export const UNCONFIRMED_SIGN_IN = "This page could not confirm whether you are signed in, and your password was not " +
  "sent again. Check whether you are signed in, or type your password to sign in again.";

export function signInOutcome(reply: Reply<Session>): SignInOutcome {
  if (reply.state === "ok") {
    return reply.data.state === "signed_in" ? { kind: "signed-in", session: reply.data }
      : { kind: "refused", detail: "Signing in did not succeed." };
  }
  if (reply.state === "unconfirmed") return { kind: "unconfirmed", detail: UNCONFIRMED_SIGN_IN };
  const registration = reply.error.registration;
  return registration ? { kind: "registration", registration } : { kind: "refused", detail: reply.error.detail };
}
