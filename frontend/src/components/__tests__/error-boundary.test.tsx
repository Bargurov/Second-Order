/**
 * Tests for ``components/error-boundary.tsx``.
 *
 * The frontend test suite runs under Vitest's default ``node``
 * environment with no jsdom / @testing-library wired in — every
 * other component test in this repo follows the same convention and
 * tests pure logic + SSR markup.  We do the same here:
 *
 *  * ``getDerivedStateFromError`` is verified as a pure function.
 *  * The default fallback's static markup is verified via
 *    ``react-dom/server.renderToStaticMarkup`` — no DOM required.
 *  * The boundary class's ``render()`` branches are exercised by
 *    instantiating the class directly and inspecting the returned
 *    React element type / props.  This pins the contract without
 *    relying on React's reconciler.
 *
 * ---------------------------------------------------------------
 * Manual visual smoke (browser, dev) — what to confirm by eye
 * ---------------------------------------------------------------
 * SSR markup assertions cover content + structure, not appearance.
 * Before merging meaningful changes to the fallback, run this list
 * in a real browser:
 *
 *  1. ``cd frontend && npm run dev``
 *  2. In any page component, drop a query-string-guarded call to
 *     ``throwForSmoke()`` (imported from ``@/components/error-boundary``)
 *     inside the render body or an effect:
 *
 *         if (import.meta.env.DEV &&
 *             new URLSearchParams(window.location.search).get("smoke-crash") === "1") {
 *           throwForSmoke();
 *         }
 *
 *     In the dev browser, append ``?smoke-crash=1`` to the page URL
 *     and reload (the host:port is whatever ``npm run dev`` printed —
 *     no literal is pinned here so the deploy-runtime no-hardcoded-
 *     host contract stays clean).  The per-page boundary in ``App.tsx``
 *     should catch and render the fallback while the sidebar / top
 *     bar stay live.
 *  3. Confirm visually:
 *       - The ``Reload page`` button reads as the primary action
 *         against the ``error-container/8`` card tint — it should
 *         dominate the action row, not blend in.
 *       - The default ``<summary>`` disclosure marker (small
 *         triangle) does not visually clash with the coral palette.
 *         Per CLAUDE.md we keep the native marker rather than
 *         ``list-none``-ing it; if the clash is unacceptable, that
 *         is a design decision to revisit.
 *       - Opening "Technical details" reveals a ``<pre>`` capped at
 *         ``max-h-40`` that scrolls cleanly without overflowing the
 *         card — paste a long synthetic stack to stress this.
 *       - Clicking "Copy details" pastes the ``buildErrorReport``
 *         output (scope + message + stack + component stack) into
 *         the clipboard and flips the label to "Copied" for ~1.8s,
 *         then back.  Verify with a real paste.
 *       - To compare scopes, also crash the outermost ``<App />``
 *         boundary (``main.tsx``) — confirm the headline reads
 *         "Something went wrong." (app scope) instead of the
 *         "This page failed to render." page-scope headline.
 *  4. **REMOVE the smoke trigger before committing.**  The
 *     ``import.meta.env.DEV`` guard makes the call dead at runtime
 *     in prod, but the *intent* of this flow is purely transient —
 *     a committed ``throwForSmoke`` call site is a bug regardless
 *     of guarding, and code review will reject it.  The helper is
 *     named with "smoke" specifically so reviewers can grep for it.
 */

import { describe, it, expect, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { isValidElement, type ErrorInfo } from "react";

import {
  ErrorBoundary,
  DefaultErrorFallback,
  throwForSmoke,
  type ErrorBoundaryFallback,
} from "../error-boundary";


// ---------------------------------------------------------------------------
// 1. ``getDerivedStateFromError`` — pure function
// ---------------------------------------------------------------------------


describe("ErrorBoundary.getDerivedStateFromError", () => {
  it("flips hasError and stores the error reference", () => {
    const err = new Error("boom");
    // ``getDerivedStateFromError`` only sets the synchronous error
    // half of state — the React component stack lands later via
    // ``componentDidCatch``.  We assert the returned partial verbatim.
    expect(ErrorBoundary.getDerivedStateFromError(err)).toEqual({
      hasError: true,
      error: err,
    });
  });

  it("preserves error identity (===) for downstream consumers", () => {
    const err = new Error("identity test");
    const next = ErrorBoundary.getDerivedStateFromError(err);
    // Strict identity — the boundary must not clone or wrap the
    // original error.  Custom fallbacks rely on the same reference.
    expect(next.error).toBe(err);
  });
});


// ---------------------------------------------------------------------------
// 2. Initial state
// ---------------------------------------------------------------------------


describe("ErrorBoundary initial state", () => {
  it("starts with hasError=false and error/info=null", () => {
    const boundary = new ErrorBoundary({ children: "n/a" });
    expect(boundary.state).toEqual({
      hasError: false,
      error: null,
      info: null,
    });
  });
});


// ---------------------------------------------------------------------------
// 3. ``render`` — children path
// ---------------------------------------------------------------------------


describe("ErrorBoundary.render — healthy", () => {
  it("returns children when state has no error", () => {
    const sentinel = "child-sentinel-text";
    const boundary = new ErrorBoundary({ children: sentinel });
    expect(boundary.render()).toBe(sentinel);
  });

  it("never invokes fallback when state is clean", () => {
    const fallback = vi.fn(() => "should-not-render");
    const boundary = new ErrorBoundary({
      children: "ok",
      fallback: fallback as unknown as ErrorBoundaryFallback,
    });
    boundary.render();
    expect(fallback).not.toHaveBeenCalled();
  });
});


// ---------------------------------------------------------------------------
// 4. ``render`` — error path with default fallback
// ---------------------------------------------------------------------------


describe("ErrorBoundary.render — default fallback", () => {
  function bootInError(scope?: string) {
    const boundary = new ErrorBoundary({ children: "irrelevant", scope });
    // Direct state mutation simulates the post-getDerivedStateFromError
    // tick — the only way React would have set this state in a real
    // crash.  Cleaner than trying to throw inside a child under SSR
    // (which doesn't trip error boundaries).  ``info`` is null because
    // ``componentDidCatch`` hasn't fired in this synthetic path.
    boundary.state = {
      hasError: true,
      error: new Error("kaboom"),
      info: null,
    };
    return boundary;
  }

  it("returns a DefaultErrorFallback element when no fallback prop is set", () => {
    const boundary = bootInError("page");
    const out = boundary.render();
    expect(isValidElement(out)).toBe(true);
    expect((out as { type: unknown }).type).toBe(DefaultErrorFallback);
  });

  it("default fallback markup carries the error message", () => {
    const boundary = bootInError("app");
    const out = boundary.render();
    const html = renderToStaticMarkup(out as any);
    expect(html).toContain("kaboom");
    expect(html).toContain("Something went wrong");
  });

  it("page-scoped default fallback uses the page-specific headline", () => {
    const boundary = bootInError("page");
    const html = renderToStaticMarkup(boundary.render() as any);
    expect(html).toContain("This page failed to render");
  });

  it("default fallback exposes a Reload button", () => {
    const boundary = bootInError("app");
    const html = renderToStaticMarkup(boundary.render() as any);
    expect(html).toContain("Reload page");
  });

  it('default fallback markup carries role="alert" for assistive tech', () => {
    const boundary = bootInError("page");
    const html = renderToStaticMarkup(boundary.render() as any);
    expect(html).toContain('role="alert"');
  });
});


// ---------------------------------------------------------------------------
// 5. ``render`` — custom fallback shapes
// ---------------------------------------------------------------------------


describe("ErrorBoundary.render — custom fallback", () => {
  it("static ReactNode fallback renders verbatim on error", () => {
    const boundary = new ErrorBoundary({
      children: "n/a",
      fallback: "literal-fallback",
    });
    boundary.state = { hasError: true, error: new Error("x"), info: null };
    expect(boundary.render()).toBe("literal-fallback");
  });

  it("function fallback receives error + reset + scope", () => {
    const fallback = vi.fn(({ error, scope }) =>
      `caught ${error.message} in ${scope ?? "?"}`,
    );
    const boundary = new ErrorBoundary({
      children: "n/a",
      fallback,
      scope: "page",
    });
    const err = new Error("rendered-failure");
    boundary.state = { hasError: true, error: err, info: null };
    const out = boundary.render();
    expect(fallback).toHaveBeenCalledTimes(1);
    const args = fallback.mock.calls[0][0];
    expect(args.error).toBe(err);
    expect(args.scope).toBe("page");
    expect(typeof args.reset).toBe("function");
    expect(out).toBe("caught rendered-failure in page");
  });
});


// ---------------------------------------------------------------------------
// 6. ``componentDidCatch`` — telemetry seam
// ---------------------------------------------------------------------------


describe("ErrorBoundary.componentDidCatch", () => {
  // Synthetic boundaries here are never mounted, so React's default
  // updater would warn on setState.  Each test stubs setState — both
  // to silence that warning and to assert the React component stack
  // is captured into state for the fallback's report.
  it("captures the React component stack via setState and forwards to onError", () => {
    const onError = vi.fn();
    const boundary = new ErrorBoundary({
      children: "n/a",
      onError,
      scope: "page",
    });
    const setStateStub = vi.fn();
    (boundary as unknown as { setState: typeof setStateStub }).setState =
      setStateStub;
    const err = new Error("wired");
    const info: ErrorInfo = { componentStack: "\n    at Foo\n" };
    boundary.componentDidCatch(err, info);
    expect(setStateStub).toHaveBeenCalledWith({ info });
    expect(onError).toHaveBeenCalledWith(err, info, "page");
  });

  it("falls back to console.error when no onError prop is provided", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      const boundary = new ErrorBoundary({ children: "n/a", scope: "app" });
      (boundary as unknown as { setState: () => void }).setState = () => {};
      boundary.componentDidCatch(new Error("default-log"), {
        componentStack: "<stack>",
      });
      expect(spy).toHaveBeenCalled();
      // Scope tag must be in the log prefix so an operator scanning
      // the console can attribute the crash.
      const firstArg = spy.mock.calls[0]?.[0];
      expect(String(firstArg)).toContain("ErrorBoundary");
      expect(String(firstArg)).toContain("app");
    } finally {
      spy.mockRestore();
    }
  });
});


// ---------------------------------------------------------------------------
// 7. ``reset`` — clears state
// ---------------------------------------------------------------------------


describe("ErrorBoundary.reset", () => {
  it("clears hasError, error, and info so subsequent renders return children", () => {
    const boundary = new ErrorBoundary({ children: "fresh-children" });
    boundary.state = {
      hasError: true,
      error: new Error("oops"),
      info: { componentStack: "\n    at Foo\n" },
    };
    // Stub setState — the real implementation is a React-managed
    // method that requires a mounted instance.  We verify reset
    // dispatches the correct payload, which is the contract.
    const setStateStub = vi.fn();
    (boundary as unknown as { setState: typeof setStateStub }).setState =
      setStateStub;
    boundary.reset();
    expect(setStateStub).toHaveBeenCalledWith({
      hasError: false,
      error: null,
      info: null,
    });
  });
});


// ---------------------------------------------------------------------------
// 8. DefaultErrorFallback — direct render
// ---------------------------------------------------------------------------


describe("DefaultErrorFallback", () => {
  it("renders the error message verbatim inside the technical details block", () => {
    const html = renderToStaticMarkup(
      <DefaultErrorFallback error={new Error("specific-error-text")} />,
    );
    expect(html).toContain("specific-error-text");
  });

  it("uses the default app-scope headline when scope is undefined", () => {
    const html = renderToStaticMarkup(
      <DefaultErrorFallback error={new Error("e")} />,
    );
    expect(html).toContain("Something went wrong");
    expect(html).not.toContain("This page failed to render");
  });

  it("switches to the page-scope headline when scope='page'", () => {
    const html = renderToStaticMarkup(
      <DefaultErrorFallback error={new Error("e")} scope="page" />,
    );
    expect(html).toContain("This page failed to render");
  });

  it("wraps technical info in a compact <details> block titled 'Technical details'", () => {
    const html = renderToStaticMarkup(
      <DefaultErrorFallback error={new Error("e")} />,
    );
    expect(html).toMatch(/<details/);
    expect(html).toContain("Technical details");
  });

  it("includes error.stack in the details block when present", () => {
    const err = new Error("stacked");
    err.stack = "Error: stacked\n    at synthetic-frame";
    const html = renderToStaticMarkup(<DefaultErrorFallback error={err} />);
    expect(html).toContain("synthetic-frame");
  });

  it("includes the React component stack when threaded through", () => {
    const err = new Error("react-crash");
    err.stack = undefined;
    const html = renderToStaticMarkup(
      <DefaultErrorFallback
        error={err}
        scope="page"
        componentStack={"\n    at MarketOverview\n    at App"}
      />,
    );
    // The component stack is what tells an operator which subtree
    // died — it MUST land in the visible report (and therefore in
    // the copied report, since the two are the same string).
    expect(html).toContain("MarketOverview");
    expect(html).toContain("component stack");
  });

  it("exposes both Reload and Copy details actions when the error has details", () => {
    const html = renderToStaticMarkup(
      <DefaultErrorFallback error={new Error("e")} />,
    );
    expect(html).toContain("Reload page");
    expect(html).toContain("Copy details");
  });

  it("renders Reload but hides Copy details + technical block when nothing is reportable", () => {
    const err = new Error("");
    err.stack = undefined;
    const html = renderToStaticMarkup(
      <DefaultErrorFallback error={err} componentStack={null} />,
    );
    // The user must always have an escape hatch.
    expect(html).toContain("Reload page");
    // Nothing to report → no Copy button, no <details> noise.
    expect(html).not.toContain("Copy details");
    expect(html).not.toMatch(/<details/);
    expect(html).not.toContain("Technical details");
  });
});


// ---------------------------------------------------------------------------
// 9. throwForSmoke — manual smoke helper
// ---------------------------------------------------------------------------


describe("throwForSmoke (manual smoke helper)", () => {
  // The unit suite cannot exercise React's reconciler-driven catch
  // path (no jsdom).  This helper exists so an operator can trip
  // the boundary in a real browser following the visual-smoke steps
  // documented at the top of this file.  These tests pin its
  // contract — a no-op helper would silently invalidate every
  // future smoke run.
  it("throws an Error tagged with the 'manual smoke' default message", () => {
    expect(() => throwForSmoke()).toThrowError(/manual smoke/);
  });

  it("forwards a custom message verbatim so callers can tag the source", () => {
    expect(() => throwForSmoke("from-page-overview")).toThrowError(
      "from-page-overview",
    );
  });

  it("throws a real Error instance (not a string) so the boundary captures stack + message", () => {
    let caught: unknown = null;
    try {
      throwForSmoke("identity-check");
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error).message).toBe("identity-check");
    // ``error.stack`` populated by V8 — the fallback's report block
    // relies on this being present for a non-empty technical view.
    expect((caught as Error).stack).toBeDefined();
  });
});
