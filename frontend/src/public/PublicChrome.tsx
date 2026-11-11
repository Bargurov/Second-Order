// The signed-out pages' frame: a skip link, the topbar with the public addresses, the page and a footer. Moving to
// another page puts focus on its heading, so keyboard and screen-reader users start at the top of what changed.
import { useEffect, useRef, type MouseEvent, type ReactNode } from "react";
import { PUBLIC_PATHS } from "../contracts/onboarding.ts";
import { Link } from "../router";
import type { PublicRoute } from "./route.ts";
import "./public.css";

const SECTION: Record<PublicRoute, string> = {
  landing: "Research workspace", register: "Register", "sign-in": "Sign in", credits: "Credits", other: "Sign in",
};

const NAV: { to: string; label: string; route: PublicRoute }[] = [
  { to: PUBLIC_PATHS.landing, label: "About", route: "landing" },
  { to: PUBLIC_PATHS.credits, label: "How credits work", route: "credits" },
  { to: PUBLIC_PATHS.register, label: "Register", route: "register" },
  { to: PUBLIC_PATHS.signIn, label: "Sign in", route: "sign-in" },
];

/** `view` names what is shown (an address, or a screen within it); when it changes, focus moves to the new heading. */
export function PublicChrome({ route, view, children }: { route: PublicRoute; view: string; children: ReactNode }) {
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {  // On the first load the browser starts at the top of the page.
      first.current = false;
      return;
    }
    main.current?.querySelector<HTMLElement>("h1")?.focus();
  }, [view]);
  const skip = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    main.current?.focus();
  };
  return (
    <>
      <a className="public-skip" href="#main" onClick={skip}>Skip to content</a>
      <div className="topbar public-topbar">
        <div className="topbar-primary">
          <Link to={PUBLIC_PATHS.landing} className="wordmark">
            <span className="wordmark-name">Second Order</span>
            <span className="wordmark-section">{SECTION[route]}</span>
          </Link>
          <nav className="site-nav" aria-label="Second Order">
            {NAV.map((item) => (
              <Link key={item.to} to={item.to} className="site-link"
                    aria-current={route === item.route ? "page" : undefined}>{item.label}</Link>
            ))}
          </nav>
        </div>
      </div>
      <main id="main" ref={main} tabIndex={-1} className="page public" data-route={route}>{children}</main>
      <footer className="site-footer public-footer">
        <p>Second Order reads the sources you supply, evidence first. It is retrospective research: not a forecast and
          not trading advice. An administrator approves every account.</p>
      </footer>
    </>
  );
}
