import { useEffect, useState, type CSSProperties } from "react";
import type { Loaded } from "../api";
import { CaseLibrarySection } from "../components/CaseLibrary";
import { LoadError, NotPrepared, Skeleton } from "../components/Chrome";
import { DraftsSection } from "../components/DraftReview";
import { EventInbox } from "../components/EventInbox";
import { EventIntake } from "../components/EventIntake";
import type { InboxItem } from "../inbox";
import { formatDay } from "../format";
import { Link } from "../router";
import { evaluationStatus, trackerSections, usageLabel } from "../tracker";
import type { DossierIndex, DossierSummary } from "../types";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

export function TrackerPage({ index, onRetry, search }: {
  index: Loaded<DossierIndex>;
  onRetry: () => void;
  search: string;
}) {
  const [prepared, setPrepared] = useState<{ id: string; revision: number } | null>(null);
  // The inbox entry last chosen for Analyze an event (a new nonce per choice), and whether that form is mid-action.
  const [chosen, setChosen] = useState<{ nonce: number; item: InboxItem } | null>(null);
  const [intakeBusy, setIntakeBusy] = useState(false);
  useEffect(() => {
    document.title = "Tracker · Second Order";
  }, []);
  // Saved drafts load on their own, so they can be reviewed when no Dossier index has been prepared.
  return (
    <>
      <FrozenCases index={index} onRetry={onRetry} />
      <CaseLibrarySection style={order(4)} />
      <EventInbox style={order(4)} busy={intakeBusy}
        onAnalyze={(item) => setChosen((current) => ({ nonce: (current?.nonce ?? 0) + 1, item }))} />
      <EventIntake style={order(4)} prefill={chosen} onBusyChange={setIntakeBusy} onPrepared={(id) => {
        setPrepared((current) => ({ id, revision: (current?.revision ?? 0) + 1 }));
      }} />
      <DraftsSection search={search} prepared={prepared} style={order(5)} />
    </>
  );
}

function FrozenCases({ index, onRetry }: { index: Loaded<DossierIndex>; onRetry: () => void }) {
  if (index.state === "loading") return <Skeleton />;
  if (index.state === "not-prepared") return <NotPrepared message={index.message} />;
  if (index.state === "error" || index.state === "missing") {
    return <LoadError message={index.message} onRetry={onRetry} subject="Tracker" />;
  }
  const { prospective, replay, researchCases } = trackerSections(index.data);

  return (
    <article className="tracker">
      <header className="tracker-header reveal" style={order(0)}>
        <p className="kicker">Tracker</p>
        <h1>Frozen hypotheses and their recorded evaluations</h1>
        <p className="lede">
          Each research case is frozen before its scored move and evaluated only by an explicit step. The sections
          below only read prepared research files; Analyze an event is a separate review workflow that never freezes
          or evaluates, and calls a model only for an explicitly approved paid request.
        </p>
      </header>

      <section className="intake-strip reveal" style={order(1)} aria-labelledby="intake-title">
        <p id="intake-title" className="intake-state">
          <span className="kicker">Research intake</span>
          <span className="intake-closed">Closed</span>
        </p>
        <p>
          {researchCases === 0 ? "No research cases are recorded. " : `${researchCases} research cases are recorded. `}
          Showcase cases never enter research scores, so this page reports no support or contradiction rates.
        </p>
      </section>

      <TrackerSection
        id="prospective"
        title="Prospective"
        note="Frozen after publication, before the scored window. Scoring starts after the freeze."
        rows={prospective}
        empty="No prospective case has been prepared."
        position={2}
      />
      <TrackerSection
        id="replay"
        title="Retrospective replays"
        note="Reconstructed after the event as illustrations; their outcomes were already known."
        rows={replay}
        empty="No retrospective replay has been prepared."
        position={3}
      />

      <p className="muted tracker-footnote">
        Fixture replays are evaluated as of {index.data.fixture_as_of.slice(0, 10)}; the active rules are{" "}
        {index.data.active_rules_version}. A stored case shows the rules recorded with its evaluation.
      </p>
    </article>
  );
}

interface SectionProps {
  id: string;
  title: string;
  note: string;
  rows: DossierSummary[];
  empty: string;
  position: number;
}

function TrackerSection({ id, title, note, rows, empty, position }: SectionProps) {
  return (
    <section className="card tracker-section reveal" style={order(position)} aria-labelledby={`${id}-title`}>
      <div className="tracker-section-head">
        <h2 id={`${id}-title`}>{title}</h2>
        <span className="tracker-count">{rows.length === 1 ? "1 case" : `${rows.length} cases`}</span>
      </div>
      <p className="card-note">{note}</p>
      {rows.length === 0 ? (
        <p className="empty">{empty}</p>
      ) : (
        <table className="tracker-table">
          <thead>
            <tr>
              <th scope="col">Published</th>
              <th scope="col">Case</th>
              <th scope="col">Usage</th>
              <th scope="col">Recorded evaluation</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const status = evaluationStatus(row);
              return (
                <tr key={row.id}>
                  <td data-label="Published">{formatDay(row.published_at)}</td>
                  <td data-label="Case">
                    <Link to={`/h/${row.id}`} className="tracker-case">{row.headline}</Link>
                    <span className="tracker-meta">{row.label}</span>
                  </td>
                  <td data-label="Usage">
                    <span className={`usage-badge usage-${row.usage}`}>{usageLabel(row.usage)}</span>
                  </td>
                  <td data-label="Recorded evaluation">
                    <span className={`verdict-chip ${status.className}`}>{status.label}</span>
                    <span className="tracker-detail">{status.detail}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
