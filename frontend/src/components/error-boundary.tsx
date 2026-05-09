/**
 * ErrorBoundary — React class boundary that traps render-phase
 * exceptions in its subtree and renders a visible fallback instead
 * of letting the whole app blank out.
 *
 * Why a class component
 * ---------------------
 * React's error-boundary contract (``getDerivedStateFromError`` /
 * ``componentDidCatch``) is the only catch surface the framework
 * exposes; there is no Hooks-equivalent.
 *
 * Used at two scopes
 * ------------------
 *  * ``main.tsx``  — wraps ``<App />`` so a crash in the layout shell
 *                    still shows a recovery UI.
 *  * ``App.tsx``   — wraps the per-page render so a crash inside one
 *                    page does not blank the surrounding sidebar /
 *                    top bar.  The wrapper is keyed by ``page`` so
 *                    navigating away resets the boundary state.
 *
 * Design constraints
 * ------------------
 * Mirrors the project's CLAUDE.md guidelines: muted-coral accent for
 * the negative state, Manrope headline + Inter body, tight 8px-max
 * radius, tonal contrast over hard borders.  No new colour tokens —
 * reuses ``error-dim`` / ``error-container`` (already defined by
 * ``DegradedBanner`` and friends).
 */

import {
  Component,
  useState,
  type ErrorInfo,
  type ReactElement,
  type ReactNode,
} from "react";

export type ErrorBoundaryFallback =
  | ReactNode
  | ((args: { error: Error; reset: () => void; scope?: string }) => ReactNode);

export interface ErrorBoundaryProps {
  children: ReactNode;
  /**
   * Override the default fallback.  Either a static node or a
   * render-prop that receives the captured error and a ``reset``
   * function so the caller can clear the boundary's error state.
   */
  fallback?: ErrorBoundaryFallback;
  /**
   * Free-text label surfaced in the default fallback and forwarded
   * to ``onError`` / ``console.error``.  Distinguishes app-level
   * crashes from page-level crashes in operator logs.
   */
  scope?: string;
  /**
   * Side-channel for telemetry / structured logging.  Defaults to
   * ``console.error`` when absent so a crash never goes silently
   * dropped.
   */
  onError?: (error: Error, info: ErrorInfo, scope?: string) => void;
}

export interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  /**
   * Captured by ``componentDidCatch`` so the React component stack
   * can flow into the default fallback's copy-details report.  Plain
   * ``error.stack`` only points at the JS throw site; the React
   * stack is what tells an operator which subtree died.
   */
  info: ErrorInfo | null;
}


// ---------------------------------------------------------------------------
// Default fallback — exported as a plain component so unit tests can
// render it via ``renderToStaticMarkup`` without spinning up a DOM.
// ---------------------------------------------------------------------------


export interface DefaultErrorFallbackProps {
  error: Error;
  scope?: string;
  /**
   * React component stack captured by the boundary (if available).
   * Threaded through from ``componentDidCatch`` so it lands in the
   * copy-details report — a JS stack alone is not enough to triage
   * a render crash.
   */
  componentStack?: string | null;
  /**
   * Optional reload handler.  When omitted, defaults to a hard
   * ``window.location.reload()`` — the safest universally-useful
   * recovery for an app-level crash and a no-op when the boundary
   * is far enough up the tree that ``reset()`` cannot rebuild.
   */
  onReload?: () => void;
}


const RELOAD_LABEL = "Reload page";
const COPY_LABEL = "Copy details";
const COPIED_LABEL = "Copied";
const DETAILS_LABEL = "Technical details";


function buildErrorReport(
  error: Error,
  scope: string | undefined,
  componentStack: string | null | undefined,
): string {
  const parts: string[] = [];
  if (scope) parts.push(`scope: ${scope}`);
  parts.push(`message: ${error.message || "(empty)"}`);
  if (error.stack) parts.push(`\nstack:\n${error.stack}`);
  if (componentStack) parts.push(`\ncomponent stack:${componentStack}`);
  return parts.join("\n");
}


export function DefaultErrorFallback(
  props: DefaultErrorFallbackProps,
): ReactElement {
  const { error, scope, componentStack, onReload } = props;
  const [copied, setCopied] = useState(false);

  const handleReload = () => {
    if (onReload) {
      onReload();
      return;
    }
    if (typeof window !== "undefined" && window.location) {
      window.location.reload();
    }
  };

  // Same string we render into the visible <pre>, so "Copy details"
  // really is "copy what you see" — no surprise drift between the
  // operator's screenshot and the report they paste into Slack.
  const report = buildErrorReport(error, scope, componentStack);
  const hasDetails = Boolean(error.message) || Boolean(error.stack) || Boolean(componentStack);

  const handleCopy = () => {
    if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
      return;
    }
    navigator.clipboard.writeText(report).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1800);
      },
      () => {
        // Permission denied or doc not focused — silent no-op; the
        // report is still visible in the <pre> for manual copy.
      },
    );
  };

  // Tonal-contrast card.  No hard borders by default — the
  // ``error-container/8`` tint plus the coral accent bar carry the
  // signal.  Title in Manrope; body quiet, monospace details hidden
  // behind a <details> disclosure to keep the card compact.
  return (
    <div
      role="alert"
      aria-live="assertive"
      data-testid="error-boundary-fallback"
      className="flex w-full justify-center px-4 py-12"
    >
      <div className="flex w-full max-w-xl gap-3 rounded-md bg-error-container/8 p-4">
        <div
          aria-hidden="true"
          className="w-1 shrink-0 rounded-sm bg-error-dim"
        />
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <p className="font-manrope text-sm font-semibold text-error-dim/90">
              {scope === "page"
                ? "This page failed to render."
                : "Something went wrong."}
            </p>
            <p className="font-inter text-xs leading-relaxed text-on-surface-variant/70">
              The interface trapped an unexpected error and replaced the
              broken view with this notice.  No data was lost.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleReload}
              className="rounded-sm bg-error-container/30 px-2.5 py-1 font-inter text-xs font-medium text-error-dim transition-colors hover:bg-error-container/40 focus-visible:outline focus-visible:outline-1 focus-visible:outline-error-dim/50"
            >
              {RELOAD_LABEL}
            </button>
            {hasDetails ? (
              <button
                type="button"
                onClick={handleCopy}
                className="rounded-sm px-2.5 py-1 font-inter text-xs font-medium text-on-surface-variant/65 transition-colors hover:text-error-dim/80 focus-visible:outline focus-visible:outline-1 focus-visible:outline-error-dim/40"
              >
                {copied ? COPIED_LABEL : COPY_LABEL}
              </button>
            ) : null}
          </div>

          {hasDetails ? (
            <details className="rounded-sm">
              <summary className="cursor-pointer px-2 py-1 font-inter text-[11px] font-medium text-on-surface-variant/55 transition-colors hover:text-on-surface-variant/75">
                {DETAILS_LABEL}
              </summary>
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-error-container/15 px-2 py-1.5 font-mono text-[11px] leading-relaxed text-on-surface-variant/65">
                {report}
              </pre>
            </details>
          ) : null}
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Manual smoke helper — dev / test only
// ---------------------------------------------------------------------------


/**
 * throwForSmoke — dev/test-only thrower for manually tripping the
 * ErrorBoundary.  Always throws; there is no env guard.  The
 * "smoke" tag in the default message + this JSDoc are the deterrent
 * against accidental prod use — review for any committed call site.
 *
 * Two intended uses
 * -----------------
 *  * **Browser smoke** (operator):  wrap the call in a query-string
 *    guard inside a page render so the fallback only trips on demand:
 *
 *        if (import.meta.env.DEV &&
 *            new URLSearchParams(window.location.search).get("smoke-crash") === "1") {
 *          throwForSmoke();
 *        }
 *
 *    Then visit ``<page>?smoke-crash=1`` to verify the fallback in
 *    real layout context.  The boundary fills in the component
 *    stack once it catches; the JS ``error.stack`` is real because
 *    this is a normal ``throw new Error(...)``.
 *
 *    **Remove the call site before committing.**  The DEV guard
 *    makes it inert in prod, but a committed smoke trigger is a
 *    code-review reject regardless — this flow is for transient
 *    local verification only.
 *
 *  * **Tests**:  the unit suite below uses this to exercise the
 *    ``componentDidCatch`` path indirectly (and pins the contract
 *    that the helper actually throws — a no-op helper would silently
 *    invalidate every smoke run).
 *
 * Why a function and not a component
 * ----------------------------------
 * One line of JS is cheaper than a new exported component, doesn't
 * grow the UI surface (per CLAUDE.md), and lets the operator decide
 * the trigger shape (effect, render branch, button onClick).  See
 * the visual-smoke docstring at the top of the test file for the
 * checks the unit tests cannot catch.
 */
export function throwForSmoke(message?: string): never {
  throw new Error(message ?? "manual smoke: ErrorBoundary fallback");
}


// ---------------------------------------------------------------------------
// ErrorBoundary class
// ---------------------------------------------------------------------------


export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { hasError: false, error: null, info: null };

  static getDerivedStateFromError(
    error: Error,
  ): Pick<ErrorBoundaryState, "hasError" | "error"> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Stash the React component stack so the default fallback's
    // copy-details report can include it.  Two separate state
    // updates (this + getDerivedStateFromError) is the React-native
    // pattern; the extra render only happens on the error path.
    this.setState({ info });
    const { onError, scope } = this.props;
    if (onError) {
      onError(error, info, scope);
      return;
    }
    // No telemetry seam wired yet — surface the crash on the console
    // so an operator opening DevTools sees it immediately.
    // eslint-disable-next-line no-console
    console.error(
      `[ErrorBoundary${scope ? `:${scope}` : ""}]`,
      error,
      info?.componentStack ?? "",
    );
  }

  reset = (): void => {
    this.setState({ hasError: false, error: null, info: null });
  };

  render(): ReactNode {
    if (this.state.hasError && this.state.error) {
      const { fallback, scope } = this.props;
      if (typeof fallback === "function") {
        return fallback({ error: this.state.error, reset: this.reset, scope });
      }
      if (fallback !== undefined) {
        return fallback;
      }
      return (
        <DefaultErrorFallback
          error={this.state.error}
          scope={scope}
          componentStack={this.state.info?.componentStack ?? null}
        />
      );
    }
    return this.props.children;
  }
}
