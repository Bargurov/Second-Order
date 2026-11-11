import type { CSSProperties } from "react";
import { Link } from "../router";
import "../library.css";

/**
 * The case library's company research: one card per company page. The list is static and reads nothing, so the
 * library never loads a company's research; the page itself verifies its documents when it is opened. Only the
 * admin build has the library, and the page's data route is admin only, as every /api route.
 */
export function CompanyList({ style }: { style?: CSSProperties }) {
  return (
    <section id="companies" className="card policy-views reveal" style={style} aria-labelledby="companies-title"
             data-companies="">
      <div className="tracker-section-head">
        <h2 id="companies-title">Company research</h2>
        <span className="tracker-count">One company</span>
      </div>
      <ol className="policy-view-list">
        <li className="policy-view-entry" data-company-card="fcx">
          <p className="library-entry-meta">
            <span className="library-category">Company</span>
            <span>Copper producer · figures to 30 Sep 2026</span>
          </p>
          <Link to="/companies/fcx" className="library-entry-title">Freeport-McMoRan (FCX)</Link>
          <p className="library-entry-summary">How the copper price reaches Freeport-McMoRan's cash flow, and what held
            its volumes back in 2026.</p>
          <p className="library-selection">
            A research view, not a valuation or a recommendation. Each figure is checked against its retained company
            document when the page is opened; the interpretation is AI-drafted and not reviewed by the owner.
          </p>
        </li>
      </ol>
    </section>
  );
}
