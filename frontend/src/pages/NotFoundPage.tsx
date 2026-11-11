import { useEffect } from "react";
import type { Loaded } from "../api";
import { CaseList } from "../components/Chrome";
import { Link } from "../router";
import type { DossierIndex } from "../types";

export function NotFoundPage({ index, what }: { index: Loaded<DossierIndex>; what: string }) {
  useEffect(() => {
    document.title = "Not found · Second Order";
  }, []);
  return (
    <section className="state-panel" aria-labelledby="missing-title">
      <p className="kicker">404 · Not found</p>
      <h1 id="missing-title">There is no Dossier at this address</h1>
      <p>{what} Dossier addresses look like <code>/h/</code> followed by a 64-character hypothesis ID.</p>
      {index.state === "ready" && index.data.dossiers.length > 0 && (
        <>
          <p className="muted">These prepared Dossiers exist:</p>
          <CaseList index={index} />
        </>
      )}
      <p>
        <Link to="/">Back to the Tracker</Link>
      </p>
    </section>
  );
}
