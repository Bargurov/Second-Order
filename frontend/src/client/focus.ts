// Keyboard and screen-reader arrival on a Client page. When the Client moves to another page (a link, or an action such
// as preparing that opens the analysis), focus would otherwise stay on a link that is gone, or fall back to the top of
// the document. Once the new page's title is shown it receives focus, so the page is announced and the next Tab starts
// from it. Focus the person has already put somewhere else is never taken away.

/** Whether focus is nowhere the person chose: the document itself, an element that has gone, or the navigation they
 * used to get here. */
function adrift(): boolean {
  const active = document.activeElement;
  return active === null || active === document.body || !active.isConnected ||
    active.closest(".client-topbar, .account-strip") !== null;
}

/** Focus the page title in `main` as soon as it is shown (pages that read first show it a moment later). Returns the
 * cleanup for the next page change. */
export function focusTitleOnArrival(main: HTMLElement | null): () => void {
  if (main === null) return () => undefined;
  const attempt = (): boolean => {
    const title = main.querySelector<HTMLElement>("h1.client-title");
    if (title === null) return false;
    if (adrift()) {
      if (!title.hasAttribute("tabindex")) title.setAttribute("tabindex", "-1");
      title.focus();
    }
    return true;
  };
  if (attempt()) return () => undefined;
  const observer = new MutationObserver(() => {
    if (attempt()) observer.disconnect();
  });
  observer.observe(main, { childList: true, subtree: true });
  const timer = window.setTimeout(() => observer.disconnect(), 10_000);
  return () => {
    observer.disconnect();
    window.clearTimeout(timer);
  };
}
