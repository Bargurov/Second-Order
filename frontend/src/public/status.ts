// A registrant's own registration, as a sign-in refusal returns it: only what the registration carries (never an
// account ID, role, credits or the administrator's reason), with times in the reader's own time zone.
import type { RegistrationStatus } from "../contracts/user.ts";
import { inZone } from "../client/time.ts";

export interface StatusView {
  title: string;
  facts: [string, string][];
  /** The server's own words for this registration. */
  detail: string;
  next: string[];
}

export function statusView(registration: RegistrationStatus, timeZone: string): StatusView {
  const facts: [string, string][] = [["Username", registration.username],
    ["Display name", registration.display_name], ["Submitted", inZone(registration.submitted_at, timeZone)]];
  if (registration.status === "pending") {
    return { title: "Your registration is waiting for approval", detail: registration.detail,
      facts: [...facts, ["Status", "Waiting for approval"]],
      next: ["An administrator approves or declines each registration. Nothing can be used until then.",
        "Approval alone allocates nothing: the administrator allocates credits and a daily allowance separately. " +
          "Once you can sign in, your account page lists any step still missing.",
        "Sign in again later to see the status. No e-mail is sent."] };
  }
  return { title: "Your registration was not approved", detail: registration.detail,
    facts: [...facts, ...(registration.decided_at ? [["Decided", inZone(registration.decided_at, timeZone)] as
      [string, string]] : []), ["Status", "Not approved"]],
    next: ["This username cannot be registered again.", "You can register under another username."] };
}
