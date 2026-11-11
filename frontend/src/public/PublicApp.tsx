// What a signed-out visitor sees in the Client build (docs/onboarding-contract.md section 7): the landing page at /,
// registration at /register, sign-in at /sign-in, how credits work at /credits, and the sign-in form at any other
// address, which it keeps so a bookmarked research page opens after signing in. A registrant whose registration is
// waiting or was not approved sees its status after signing in, with no session. Page loads only read; a registration
// or sign-in is sent only when the person submits it, never retried, and no password is kept beyond its form.
import { useEffect, useState } from "react";
import { PUBLIC_PATHS, type PublicAppProps } from "../contracts/onboarding.ts";
import type { RegistrationStatus, Session } from "../contracts/user.ts";
import { Link, navigate, useLocation } from "../router";
import { SignIn, type SignInProps } from "../shell/SignIn";
import { CreditsGuide } from "./CreditsGuide";
import { Landing } from "./Landing";
import { PublicChrome } from "./PublicChrome";
import { Register } from "./Register";
import { RegistrationStatusView } from "./RegistrationStatus";
import { afterSignIn, publicRoute } from "./route.ts";

export function PublicApp({ reason, onSignedIn }: PublicAppProps) {
  const { pathname } = useLocation();
  const route = publicRoute(pathname);
  /** A registrant's status, shown where they signed in until they move on. */
  const [status, setStatus] = useState<{ path: string; registration: RegistrationStatus } | null>(null);
  /** The username to start the sign-in form with after "Check by signing in". */
  const [checking, setChecking] = useState<string | null>(null);

  const signIn: SignInProps = {
    reason,
    onSignedIn: (session: Session) => {
      const home = afterSignIn(pathname);
      if (home) navigate(home, { replace: true });
      onSignedIn(session);
    },
    onRegistration: (registration) => {
      setChecking(null);
      setStatus({ path: pathname, registration });
    },
    footer: <>No account yet? <Link to={PUBLIC_PATHS.register}>Register</Link>; an administrator approves every
      account.</>,
  };
  const shownStatus = status?.path === pathname ? status.registration : null;

  let page;
  if (shownStatus) {
    page = <RegistrationStatusView registration={shownStatus} onSignInAgain={() => setStatus(null)} />;
  } else if (route === "landing") {
    page = <Landing reason={reason} />;
  } else if (route === "register") {
    page = <Register onCheck={(username) => {
      setChecking(username);
      navigate(PUBLIC_PATHS.signIn);
    }} />;
  } else if (route === "credits") {
    page = <CreditsPublic signIn={signIn} />;
  } else {
    page = <SignInPage key={checking ?? ""} signIn={signIn} other={route === "other"} checking={checking} />;
  }
  return <PublicChrome route={route} view={`${pathname}${shownStatus ? `#${shownStatus.status}` : ""}`}>{page}</PublicChrome>;
}

function SignInPage({ signIn, other, checking }: { signIn: SignInProps; other: boolean; checking: string | null }) {
  useEffect(() => { document.title = "Sign in · Second Order"; }, []);
  const context = other ? "Sign in to open this page."
    : checking ? "Sign in with the username and password you registered with. A registration waiting for approval " +
      "shows its status. If the server says the username or password is not correct, either the password differs or " +
      "the registration was not recorded, and you can register again."
    : null;
  return <SignIn {...signIn} username={checking ?? ""} context={context} />;
}

/** How credits work, for a visitor; signing in here keeps the address and shows the user's own credits. */
function CreditsPublic({ signIn }: { signIn: SignInProps }) {
  const [signingIn, setSigningIn] = useState(false);
  useEffect(() => { document.title = "How credits work · Second Order"; }, []);
  return (
    <div className="public-credits" data-public="credits">
      <header className="public-hero is-compact">
        <p className="kicker">Credits</p>
        <h1 tabIndex={-1}>How credits work</h1>
        <p className="public-lede">Credits are points of usage on this server, with no money value. Every analysis is
          quoted before it runs, and nothing runs until you approve the quote.</p>
      </header>
      <aside className="card public-card public-own" aria-label="Your own credits">
        {signingIn ? <SignIn {...signIn} context="Your credits and allowance open here after you sign in." />
          : <>
            <p>Signed in, this page also shows your own credits, today's allowance and any step still missing.</p>
            <p className="public-actions"><button type="button" className="button button-quiet"
                                                  onClick={() => setSigningIn(true)}>Sign in to see your own credits</button></p>
          </>}
      </aside>
      <CreditsGuide />
    </div>
  );
}
