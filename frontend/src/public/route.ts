// The signed-out pages' addresses (docs/onboarding-contract.md section 7). Any other address shows the sign-in form and
// keeps the address, so a bookmarked research page opens after signing in.
import { PUBLIC_PATHS } from "../contracts/onboarding.ts";

export type PublicRoute = "landing" | "register" | "sign-in" | "credits" | "other";

export function publicRoute(pathname: string): PublicRoute {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  if (path === PUBLIC_PATHS.landing || path === "/client.html") return "landing";
  if (path === PUBLIC_PATHS.register) return "register";
  if (path === PUBLIC_PATHS.signIn) return "sign-in";
  if (path === PUBLIC_PATHS.credits) return "credits";
  return "other";
}

/** Where the Client opens after a sign-in begun at `pathname`: its home after the landing, registration or sign-in
 * page; otherwise null, and it stays at that address (/credits, or a bookmarked research page). */
export function afterSignIn(pathname: string): string | null {
  const route = publicRoute(pathname);
  return route === "landing" || route === "register" || route === "sign-in" ? PUBLIC_PATHS.landing : null;
}
