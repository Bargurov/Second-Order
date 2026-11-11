import type { ReactNode } from "react";
import type { Loaded } from "../api";
import { caseStatus, formatDay } from "../format";
import { Link } from "../router";
import type { DossierIndex } from "../types";

export type Section = "tracker" | "analyses" | "hypotheses" | "findings" | "copper" | "market-context" | "fuels"
  | "library" | "method" | "dossier" | "event";

const SECTION_LABEL: Record<Section, string> = {
  tracker: "Tracker", analyses: "My analyses", hypotheses: "Hypotheses", findings: "Findings",
  copper: "Copper",  // The copper desk and its comparisons; the other copper pages stay under the library.
  "market-context": "Market context",
  fuels: "Fuels",
  library: "Case library",
  method: "Method", dossier: "Dossier", event: "Event overview",  // A private overview: no nav link of its own.
};

export function TopBar({ index, section, currentId }: {
  index: Loaded<DossierIndex>;
  section: Section | null;
  currentId?: string;
}) {
  const dossiers = index.state === "ready" ? index.data.dossiers : [];
  const current = (target: Section) => (section === target ? "page" : undefined);
  return (
    <div className="topbar">
      <div className="topbar-primary">
        <Link to="/" className="wordmark">
          <span className="wordmark-name">Second Order</span>
          {section && <span className="wordmark-section">{SECTION_LABEL[section]}</span>}
        </Link>
        <nav className="site-nav" aria-label="Sections">
          <Link to="/" className="site-link" aria-current={current("tracker")}>Tracker</Link>
          <Link to="/analyses" className="site-link" aria-current={current("analyses")}>My analyses</Link>
          <Link to="/hypotheses" className="site-link" aria-current={current("hypotheses")}>Hypotheses</Link>
          <Link to="/findings" className="site-link" aria-current={current("findings")}>Findings</Link>
          <Link to="/copper" className="site-link" aria-current={current("copper")}>Copper</Link>
          <Link to="/market-context" className="site-link" aria-current={current("market-context")}>Market context</Link>
          <Link to="/fuels" className="site-link" aria-current={current("fuels")}>Fuels</Link>
          <Link to="/library" className="site-link" aria-current={current("library")}>Library</Link>
          <Link to="/method" className="site-link" aria-current={current("method")}>Method</Link>
        </nav>
      </div>
      {dossiers.length > 0 && (
        <nav className="case-nav" aria-label="Showcase cases">
          {dossiers.map((row, i) => {
            const status = caseStatus(row);
            return (
              <Link
                key={row.id}
                to={`/h/${row.id}`}
                className={`case-link${row.id === currentId ? " is-current" : ""}`}
                aria-current={row.id === currentId ? "page" : undefined}
              >
                <span className="case-number">{String(i + 1).padStart(2, "0")}</span>
                <span className="case-date">{formatDay(row.published_at)}</span>
                <span className={`case-verdict ${status.className}`}>{status.label}</span>
              </Link>
            );
          })}
        </nav>
      )}
    </div>
  );
}

export function Page({ children }: { children: ReactNode }) {
  return <main className="page">{children}</main>;
}

export function NotPrepared({ message }: { message: string }) {
  return (
    <section className="state-panel" role="status">
      <p className="kicker">Not prepared</p>
      <h1>The Dossiers have not been prepared yet</h1>
      <p>{message}</p>
      <pre><code>python -m second_order prepare</code></pre>
      <p className="muted">
        Preparation is the explicit step that evaluates the committed offline fixtures and, with <code>--db</code>,
        reads frozen cases and their stored evaluations from a store. This page only reads its output; it never
        evaluates, calls a model or fetches market data.
      </p>
    </section>
  );
}

export function LoadError({ message, onRetry, subject = "Dossier" }: {
  message: string;
  onRetry: () => void;
  subject?: string;
}) {
  return (
    <section className="state-panel" role="alert">
      <p className="kicker">Could not load</p>
      <h1>The {subject} could not be loaded</h1>
      <p>{message}</p>
      <button type="button" className="button" onClick={onRetry}>Try again</button>
    </section>
  );
}

export function CaseList({ index }: { index: Loaded<DossierIndex> }) {
  if (index.state !== "ready") return null;
  return (
    <ol className="case-list">
      {index.data.dossiers.map((row) => {
        const status = caseStatus(row);
        return (
          <li key={row.id}>
            <Link to={`/h/${row.id}`} className="case-card">
              <span className="case-card-meta">
                {formatDay(row.published_at)} · {row.label}
              </span>
              <span className="case-card-headline">{row.headline}</span>
              <span className={`verdict-chip ${status.className}`}>{status.label}</span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}

export function Skeleton() {
  return (
    <div className="skeleton" role="status" aria-label="Loading the Dossier">
      <div className="sk sk-stamp" />
      <div className="sk sk-title" />
      <div className="sk sk-title short" />
      <div className="sk-grid">
        <div className="sk sk-block" />
        <div className="sk sk-block" />
      </div>
      <div className="sk sk-wide" />
    </div>
  );
}
