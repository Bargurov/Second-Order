import { useEffect, useState, type AnchorHTMLAttributes, type MouseEvent } from "react";
import { mayLeave } from "./leave";

// Two routes do not need a router library: real paths, history API, server fallback to index.html.
const NAVIGATE = "second-order:navigate";
const ask = (question: string) => window.confirm(question);

/** Go to `to`, unless a page with unsaved work is told to stay. Returns whether the app went. */
export function navigate(to: string, options: { replace?: boolean } = {}): boolean {
  if (!mayLeave(new URL(to, window.location.href).pathname, ask)) return false;
  if (options.replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  window.dispatchEvent(new Event(NAVIGATE));
  return true;
}

export function useLocation(): { pathname: string; search: string } {
  const read = () => ({ pathname: window.location.pathname, search: window.location.search });
  const [location, setLocation] = useState(read);
  useEffect(() => {
    let shown = window.location.href;
    const update = () => {
      shown = window.location.href;
      setLocation(read());
    };
    // Back and Forward change the address before the app hears of them; staying puts back the address shown.
    const popped = () => {
      if (mayLeave(window.location.pathname, ask)) update();
      else window.history.pushState(null, "", shown);
    };
    window.addEventListener("popstate", popped);
    window.addEventListener(NAVIGATE, update);
    return () => {
      window.removeEventListener("popstate", popped);
      window.removeEventListener(NAVIGATE, update);
    };
  }, []);
  return location;
}

export function Link({ to, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) {
  const follow = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    event.preventDefault();
    if (navigate(to)) window.scrollTo({ top: 0 });
  };
  return <a href={to} onClick={follow} {...rest} />;
}
