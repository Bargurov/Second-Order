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

import { Component, type ErrorInfo, type ReactElement, type ReactNode } from "react";

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
}


// ---------------------------------------------------------------------------
// Default fallback — exported as a plain component so unit tests can
// render it via ``renderToStaticMarkup`` without spinning up a DOM.
// ---------------------------------------------------------------------------


export interface DefaultErrorFallbackProps {
  error: Error;
  scope?: string;
  /**
   * Optional reload handler.  When omitted, defaults to a hard
   * ``window.location.reload()`` — the safest universally-useful
   * recovery for an app-level crash and a no-op when the boundary
   * is far enough up the tree that ``reset()`` cannot rebuild.
   */
  onReload?: () => void;
}


const RELOAD_LABEL = "Reload page";


export function DefaultErrorFallback(
  props: DefaultErrorFallbackProps,
): ReactElement {
  const { error, scope, onReload } = props;
  const handleReload = () => {
    if (onReload) {
      onReload();
      return;
    }
    if (typeof window !== "undefined" && window.location) {
      window.location.reload();
    }
  };
  // Tonal-contrast card.  No hard borders by default — the
  // ``error-container/8`` tint plus the coral accent bar carry the
  // signal.  Title in Manrope; error text quiet, monospace-friendly.
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
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <p className="font-manrope text-sm font-semibold text-error-dim/90">
            {scope === "page"
              ? "This page failed to render."
              : "Something went wrong."}
          </p>
          <p className="font-inter text-xs leading-relaxed text-on-surface-variant/70">
            The interface trapped an unexpected error and replaced the
            broken view with this notice.  No data was lost.
          </p>
          {error.message ? (
            <p className="break-words font-mono text-[11px] leading-relaxed text-on-surface-variant/55">
              {error.message}
            </p>
          ) : null}
          <div className="pt-1">
            <button
              type="button"
              onClick={handleReload}
              className="rounded-sm bg-error-container/20 px-2.5 py-1 font-inter text-xs font-medium text-error-dim/80 transition-colors hover:bg-error-container/30 focus-visible:outline focus-visible:outline-1 focus-visible:outline-error-dim/40"
            >
              {RELOAD_LABEL}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// ErrorBoundary class
// ---------------------------------------------------------------------------


export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
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
    this.setState({ hasError: false, error: null });
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
      return <DefaultErrorFallback error={this.state.error} scope={scope} />;
    }
    return this.props.children;
  }
}
