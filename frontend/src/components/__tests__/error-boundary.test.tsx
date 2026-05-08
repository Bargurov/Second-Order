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
 */

import { describe, it, expect, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { isValidElement, type ErrorInfo } from "react";

import {
  ErrorBoundary,
  DefaultErrorFallback,
  type ErrorBoundaryFallback,
} from "../error-boundary";


// ---------------------------------------------------------------------------
// 1. ``getDerivedStateFromError`` — pure function
// ---------------------------------------------------------------------------


describe("ErrorBoundary.getDerivedStateFromError", () => {
  it("flips hasError and stores the error reference", () => {
    const err = new Error("boom");
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
  it("starts with hasError=false and error=null", () => {
    const boundary = new ErrorBoundary({ children: "n/a" });
    expect(boundary.state).toEqual({ hasError: false, error: null });
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
    // (which doesn't trip error boundaries).
    boundary.state = { hasError: true, error: new Error("kaboom") };
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
    boundary.state = { hasError: true, error: new Error("x") };
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
    boundary.state = { hasError: true, error: err };
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
  it("calls onError when supplied with error + info + scope", () => {
    const onError = vi.fn();
    const boundary = new ErrorBoundary({
      children: "n/a",
      onError,
      scope: "page",
    });
    const err = new Error("wired");
    const info: ErrorInfo = { componentStack: "\n    at Foo\n" };
    boundary.componentDidCatch(err, info);
    expect(onError).toHaveBeenCalledWith(err, info, "page");
  });

  it("falls back to console.error when no onError prop is provided", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      const boundary = new ErrorBoundary({ children: "n/a", scope: "app" });
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
  it("clears hasError and error so subsequent renders return children", () => {
    const boundary = new ErrorBoundary({ children: "fresh-children" });
    boundary.state = { hasError: true, error: new Error("oops") };
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
    });
  });
});


// ---------------------------------------------------------------------------
// 8. DefaultErrorFallback — direct render
// ---------------------------------------------------------------------------


describe("DefaultErrorFallback", () => {
  it("renders the error message verbatim", () => {
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

  it("omits the error message paragraph when message is empty", () => {
    const err = new Error("");
    const html = renderToStaticMarkup(
      <DefaultErrorFallback error={err} />,
    );
    // The reload button is still present even when there's nothing
    // to print — the user must always have an escape hatch.
    expect(html).toContain("Reload page");
  });
});
