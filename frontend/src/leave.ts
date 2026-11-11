// Asking before the app leaves unsaved work. A page registers a check; the router asks every check before it
// changes the page, for links and for Back and Forward. The browser's own unload is guarded separately.

/** Given the path the app would show next: a question to confirm, or null to let it go. */
export type LeaveCheck = (pathname: string) => string | null;

const checks = new Set<LeaveCheck>();

/** Register a check; returns the function that removes it (an effect's cleanup). */
export function guardLeaving(check: LeaveCheck): () => void {
  checks.add(check);
  return () => {
    checks.delete(check);
  };
}

/** Whether the app may go to `pathname`. Each check's question is asked; one "no" keeps the page. */
export function mayLeave(pathname: string, confirm: (question: string) => boolean): boolean {
  for (const check of checks) {
    const question = check(pathname);
    if (question !== null && !confirm(question)) return false;
  }
  return true;
}
