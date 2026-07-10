/**
 * Mission J evidence card — the Evidence Overview flagship section.
 *
 * First in-product consumer of the published Mission J record
 * (`GET /evidence/mission-j`, contract mission-j-evidence-v1).  Every
 * research value rendered here comes from the endpoint payload — the
 * backend parses the tracked J1B/J2/J3 publications at request time, so
 * this card carries no hand-copied research figure and re-runs no
 * adjudication.
 *
 * Visual language translated from the Executive Design package
 * (design/Executive Design .zip → Evidence Overview prototype) into the
 * maintained tokens: hairline-gap ledger grids for dense numeric cells,
 * left-rule result blocks, bordered mono state chips with a dot (never
 * color-only), interpretive italic notes, em-dash negation list for the
 * claim limits, and tiny mono provenance footers.  The prototype's gold
 * accent maps to `primary`; its serif display roles map to the project
 * type stack.  No animated flow, no strength/rank presentation; ORDINARY
 * / UNRESOLVED and UNADJUDICABLE render at equal weight to ELEVATED.
 *
 * Server ordering is preserved everywhere; loading, unavailable, and
 * malformed states invent no value.
 */
import type {
  MissionJEvidenceSummary,
  MissionJStateBearingCell,
} from "@/lib/api";

export interface MissionJEvidenceCardProps {
  /** Endpoint payload; `null` / `undefined` renders the loading state. */
  data?: MissionJEvidenceSummary | null;
  /** Explicit degraded state when the contract could not be loaded. */
  unavailable?: boolean;
}

/** "ORDINARY_UNRESOLVED" → "ORDINARY / UNRESOLVED" (display only). */
function stateLabel(state: string): string {
  return state.replace(/_/g, " / ");
}

/** Strip the payload's markdown bold markers for plain rendering. */
function plain(text: string): string {
  return text.replace(/\*\*/g, "");
}

function Kicker({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-on-surface-variant/55">
      {children}
    </p>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[11.5px] italic leading-relaxed text-on-surface-variant/70">
      {children}
    </p>
  );
}

function Provenance({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[10px] leading-relaxed text-on-surface-variant/50">
      {children}
    </p>
  );
}

/**
 * Bordered mono chip with a dot — the prototype's state treatment.
 * Elevated uses the single chromatic accent; neutral states use slate at
 * IDENTICAL size, weight, and border so no state reads as a winner, and
 * the text label always carries the meaning (never color alone).
 */
function StateChip({ state }: { state: string }) {
  const elevated = state === "ELEVATED";
  const tone = elevated
    ? "border-primary/40 text-primary"
    : "border-on-surface-variant/40 text-on-surface-variant";
  const dot = elevated ? "bg-primary" : "bg-on-surface-variant";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-px font-mono text-[10px] uppercase tracking-[0.1em] ${tone}`}
    >
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {stateLabel(state)}
    </span>
  );
}

const CELL_TH =
  "px-2 py-1 text-left font-mono text-[9.5px] font-medium uppercase tracking-[0.08em] text-on-surface-variant/55";
const CELL_TD = "px-2 py-1 font-mono text-[11px] tabular-nums";

function StateBearingRows({ cells }: { cells: MissionJStateBearingCell[] }) {
  return (
    <>
      {cells.map((c) => (
        <tr key={c.cell} className="border-t border-border/30">
          <td className={`${CELL_TD} text-on-surface-variant/60`}>{c.cell}</td>
          <td className={`${CELL_TD} text-on-surface`}>
            {c.measurement ?? c.metric}
          </td>
          <td className={`${CELL_TD} text-on-surface-variant/85`}>
            {c.lens ?? c.window}
          </td>
          {c.role !== undefined && (
            <td className={`${CELL_TD} text-on-surface-variant/70`}>{c.role}</td>
          )}
          {c.m_class !== undefined && (
            <td className={CELL_TD}>{c.m_class}</td>
          )}
          <td className={CELL_TD}>
            {c.available_event_n} / {c.attempted_event_n}
          </td>
          <td className={CELL_TD}>{c.reference_n}</td>
          <td className={`${CELL_TD} text-on-surface`}>{c.memp}</td>
          <td className={CELL_TD}>{c.calibration_percentile}</td>
          <td className="px-2 py-1">
            <StateChip state={c.node_state} />
          </td>
          <td className={CELL_TD}>{c.loyo}</td>
          <td className={CELL_TD}>{c.loeo}</td>
          <td className={`${CELL_TD} text-on-surface-variant/85`}>
            {c.f3_sign_flip ? "flip" : "no flip"} ({c.f3_reference_n} →{" "}
            {c.f3_canonical_n})
          </td>
        </tr>
      ))}
    </>
  );
}

function isContractShaped(data: MissionJEvidenceSummary): boolean {
  return Boolean(
    data &&
      Array.isArray(data.j1b?.cells) &&
      Array.isArray(data.j1b?.panels) &&
      Array.isArray(data.j2?.state_bearing) &&
      Array.isArray(data.j2?.diagnostics) &&
      Array.isArray(data.j3?.nodes) &&
      Array.isArray(data.j3?.edges) &&
      data.j2?.collisions &&
      data.provenance?.sources,
  );
}

export function MissionJEvidenceCard({
  data,
  unavailable = false,
}: MissionJEvidenceCardProps) {
  if (unavailable) {
    return (
      <div className="flex flex-col gap-1 rounded-md border border-border/50 p-3 text-[12.5px] leading-relaxed text-on-surface-variant/85">
        <Kicker>record unavailable</Kicker>
        <p>
          Mission J record unavailable: the <code>/evidence/mission-j</code>{" "}
          contract could not be loaded (tracked-artifact drift or unreachable
          source). No figures are shown in its place.
        </p>
      </div>
    );
  }
  if (!data) {
    return (
      <p className="text-[12.5px] leading-relaxed text-on-surface-variant/70">
        Loading the Mission J robustness record&hellip;
      </p>
    );
  }
  if (!isContractShaped(data)) {
    return (
      <div className="flex flex-col gap-1 rounded-md border border-border/50 p-3 text-[12.5px] leading-relaxed text-on-surface-variant/85">
        <Kicker>record unavailable</Kicker>
        <p>
          Mission J record unavailable: the <code>/evidence/mission-j</code>{" "}
          payload did not match the expected contract. No figures are shown in
          its place.
        </p>
      </div>
    );
  }

  const { j1b, j2, j3, provenance } = data;
  const elevatedCells = j1b.cells.filter(
    (c) => c.node_state === "ELEVATED",
  ).length;
  const ceiling = j3.supports.find((s) =>
    s.includes("mechanism-consistent descriptive pattern"),
  );
  const classB = j3.supports.find((s) => s.includes("Class B"));

  return (
    <div className="flex flex-col gap-5 text-[12.5px] leading-relaxed text-on-surface/85">
      {/* A — provenance ribbon: frozen · published · no new statistics */}
      <div className="flex flex-col gap-1 border-b border-border/30 pb-3">
        <Kicker>frozen protocol · published record · no new statistics</Kicker>
        <p className="text-[11.5px] text-on-surface-variant/80">
          {provenance.publication_status}
        </p>
        <p className="text-[11.5px] text-on-surface-variant/80">
          {provenance.no_recompute_statement}
        </p>
      </div>

      {/* B — mechanism readout: frozen roles, then edges, as a ledger */}
      <div className="flex flex-col gap-2">
        <Kicker>Mechanism readout · frozen roles and edges · J3</Kicker>
        <div className="grid grid-cols-1 gap-px overflow-hidden rounded-md bg-white/[0.06] sm:grid-cols-2">
          {j3.nodes.map((n) => (
            <div
              key={n.node}
              className="flex flex-col gap-1 bg-surface-container-low p-3"
            >
              <p className="font-mono text-[11px] text-on-surface">
                <span className="text-on-surface-variant/55">{n.node}</span>{" "}
                {n.role}
              </p>
              {n.panel.length > 0 && (
                <p className="font-mono text-[10.5px] text-on-surface-variant/85">
                  {n.panel
                    .map(
                      (m) =>
                        `${m.member}${m.primary ? " (primary, " : " ("}${m.m_class}): ${m.state}`,
                    )
                    .join(" · ")}
                </p>
              )}
              {n.modifier && (
                <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-on-surface-variant/70">
                  {n.modifier}
                </p>
              )}
              <p className="text-[11px] text-on-surface-variant/80">
                reading {n.reading} — {n.rule_path}
              </p>
              <Note>{n.limitation}</Note>
            </div>
          ))}
        </div>
        <div className="flex flex-col gap-2">
          {j3.edges.map((e) => (
            <div
              key={e.edge}
              className="flex flex-col gap-1 border-l-2 border-primary/40 bg-surface-container-low p-3 pl-3"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="font-mono text-[11px] text-on-surface">
                  <span className="text-on-surface-variant/55">{e.edge}</span>{" "}
                  {e.from} <span aria-hidden>→</span>{" "}
                  <span className="sr-only">to</span>
                  {e.to}
                </p>
                <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-primary">
                  {e.state} under the frozen measurement rules
                </span>
              </div>
              <p className="text-[11px] text-on-surface-variant/80">
                upstream: {e.upstream_reading} — {e.upstream_path}
              </p>
              <p className="text-[11px] text-on-surface-variant/80">
                downstream: {stateLabel(e.downstream_state)} (
                {e.downstream_m_class}; {e.downstream_modifier})
              </p>
              <p className="text-[11px] text-on-surface-variant/80">
                {e.rule_path}
              </p>
            </div>
          ))}
        </div>
        <Note>
          {j1b.contextual_2s10s.measurement} —{" "}
          {j1b.contextual_2s10s.isolation_note} (published state{" "}
          {j1b.contextual_2s10s.state}, as context only).
        </Note>
      </div>

      {/* C — J1B robustness record */}
      <div className="flex flex-col gap-2 border-t border-border/30 pt-3">
        <Kicker>J1B · asset &amp; benchmark robustness · window {j1b.window}</Kicker>
        <p className="text-on-surface">
          <span className="font-mono tabular-nums">
            {elevatedCells}/{j1b.cells.length}
          </span>{" "}
          frozen cells {stateLabel("ELEVATED")} &middot; all{" "}
          {j1b.panels.length} panels at their published modifier:
        </p>
        <div className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[10.5px] text-on-surface-variant/85">
          {j1b.panels.map((p) => (
            <span key={p.role}>
              {p.role} ({p.members.join(", ")}; primary {p.primary}):{" "}
              <span className="text-on-surface">{p.modifier}</span>
            </span>
          ))}
        </div>
        <Note>{j1b.correlated_views_disclosure}.</Note>
        <Note>{j1b.measurement_limited.statement}.</Note>
        <div className="overflow-x-auto rounded-md border border-border/40">
          <table className="w-full min-w-[860px] border-collapse">
            <caption className="sr-only">
              J1B 12-cell robustness surface in frozen order
            </caption>
            <thead>
              <tr>
                {["#", "measurement", "lens", "role", "M", "events avail / att", "ref N", "MEMP", "calib pct", "state", "LOYO", "LOEO", "F3"].map(
                  (h) => (
                    <th key={h} scope="col" className={CELL_TH}>
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              <StateBearingRows cells={j1b.cells} />
            </tbody>
          </table>
        </div>
        {j1b.cells
          .filter((c) => (c.unavailable_events ?? []).length > 0)
          .map((c) => (
            <Provenance key={c.cell}>
              cell {c.cell} unavailable event{" "}
              {(c.unavailable_events ?? [])
                .map(([d, reason]) => `${d}: ${reason}`)
                .join(" · ")}
            </Provenance>
          ))}
      </div>

      {/* D — J2 timing challenge */}
      <div className="flex flex-col gap-2 border-t border-border/30 pt-3">
        <Kicker>J2 · pre-event timing challenge · window {j2.window}</Kicker>
        <div className="grid grid-cols-1 gap-px overflow-hidden rounded-md bg-white/[0.06] sm:grid-cols-2 lg:grid-cols-4">
          {j2.state_bearing.map((c) => (
            <div
              key={c.cell}
              className="flex flex-col gap-1 bg-surface-container-low p-3"
            >
              <p className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-on-surface-variant/55">
                cell {c.cell} · {c.metric}
              </p>
              <StateChip state={c.node_state} />
              <p className="font-mono text-[10.5px] tabular-nums text-on-surface-variant/85">
                MEMP {c.memp} · calib {c.calibration_percentile}
              </p>
              <p className="font-mono text-[10.5px] tabular-nums text-on-surface-variant/70">
                {c.available_event_n} / {c.attempted_event_n} events · ref{" "}
                {c.reference_n}
              </p>
              <p className="font-mono text-[10.5px] tabular-nums text-on-surface-variant/70">
                LOYO {c.loyo} · LOEO {c.loeo} ·{" "}
                {c.f3_sign_flip ? "F3 flip" : "F3 no flip"}
              </p>
            </div>
          ))}
        </div>
        <p className="text-[11.5px] text-on-surface-variant/80">
          {j3.timing_qualifier}
        </p>
        <Note>
          Raw-cell fragility ({j2.raw_cell_fragility.metric}): LOYO{" "}
          {j2.raw_cell_fragility.loyo} · LOEO {j2.raw_cell_fragility.loeo} —{" "}
          {j2.raw_cell_fragility.note}.
        </Note>
        <div className="flex flex-col gap-1.5 border-t border-border/30 pt-2">
          <Kicker>Descriptive [-20, -1] diagnostics</Kicker>
          <Note>
            {j2.diagnostics[0]?.status_wording}. Descriptive-only by frozen
            design — no MEMP, no calibration, no state.
          </Note>
          <div className="overflow-x-auto rounded-md border border-border/40">
            <table className="w-full min-w-[560px] border-collapse">
              <caption className="sr-only">
                Descriptive timing diagnostics D1 to D4, stateless by design
              </caption>
              <thead>
                <tr>
                  {["diag", "metric", "events avail / att", "median response", "median |response|", "direction"].map(
                    (h) => (
                      <th key={h} scope="col" className={CELL_TH}>
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {j2.diagnostics.map((d) => (
                  <tr key={d.id} className="border-t border-border/30">
                    <td className={`${CELL_TD} text-on-surface`}>{d.id}</td>
                    <td className={`${CELL_TD} text-on-surface-variant/85`}>
                      {d.metric}
                    </td>
                    <td className={CELL_TD}>
                      {d.available_event_n} / {d.attempted_event_n}
                    </td>
                    <td className={CELL_TD}>{d.median_response}</td>
                    <td className={CELL_TD}>{d.median_abs_response}</td>
                    <td className={`${CELL_TD} text-on-surface-variant/85`}>
                      {d.direction}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* E — collision qualification; C1 unadjudicability at full weight */}
      <div className="flex flex-col gap-2 border-t border-border/30 pt-3">
        <Kicker>Exact-window collision qualification · interval {j2.collisions.interval}</Kicker>
        <div className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] tabular-nums text-on-surface-variant/80">
          <span>
            primary denominator{" "}
            <span className="text-on-surface">{j2.collisions.primary_n}</span>
          </span>
          <span>
            known-register collision-free{" "}
            <span className="text-on-surface">
              {j2.collisions.collision_free_n}
            </span>
          </span>
          <span>
            C2 exact-window tags{" "}
            <span className="text-on-surface">
              {j2.collisions.c2.tagged_n} of {j2.collisions.c2.of}
            </span>
          </span>
        </div>
        <p className="text-[11.5px] text-on-surface-variant/80">
          C2 register {j2.collisions.c2.register} (
          {j2.collisions.c2.register_dates} calendar dates); the C2-tagged
          subset is{" "}
          <span className="text-on-surface">
            {j2.collisions.c2.subset_status}
          </span>
          . FOMC self-collision invariant holds (minimum anchor spacing{" "}
          {j2.collisions.fomc_self.min_anchor_spacing},{" "}
          {j2.collisions.fomc_self.violations} violations).
        </p>
        <div className="flex flex-col gap-1 border-l-2 border-on-surface-variant/50 bg-surface-container-low p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <Kicker>C1 · {j2.collisions.c1.families}</Kicker>
            <span className="inline-flex items-center gap-1.5 rounded-sm border border-on-surface-variant/40 px-1.5 py-px font-mono text-[10px] uppercase tracking-[0.1em] text-on-surface-variant">
              <span
                aria-hidden
                className="h-1.5 w-1.5 rounded-full bg-on-surface-variant"
              />
              {j2.collisions.c1.status.toUpperCase()}
            </span>
          </div>
          <p className="text-[11.5px] text-on-surface-variant/85">
            {j2.collisions.c1.reason}
          </p>
        </div>
        <Note>{j2.collisions.limitation}.</Note>
      </div>

      {/* F — claim limits: the prototype's negation-ledger treatment */}
      <div className="flex flex-col gap-1.5 border-t border-border/30 pt-3">
        <Kicker>Claim limits · what this record does not establish</Kicker>
        {classB && (
          <p className="text-[11.5px] text-on-surface-variant/80">
            {plain(classB)}
          </p>
        )}
        {ceiling && (
          <p className="text-[11.5px] text-on-surface-variant/80">
            Ceiling: {plain(ceiling)}
          </p>
        )}
        <ul className="flex flex-col gap-0.5">
          {j3.non_claims.map((line) => (
            <li key={line} className="flex items-baseline gap-2">
              <span
                aria-hidden
                className="font-mono text-[10px] text-on-surface-variant/45"
              >
                &mdash;
              </span>
              <span className="text-[11.5px] text-on-surface-variant/75">
                {line}
              </span>
            </li>
          ))}
          <li className="flex items-baseline gap-2">
            <span
              aria-hidden
              className="font-mono text-[10px] text-on-surface-variant/45"
            >
              &mdash;
            </span>
            <span className="text-[11.5px] text-on-surface-variant/75">
              {j1b.measurement_limited.statement};
            </span>
          </li>
          <li className="flex items-baseline gap-2">
            <span
              aria-hidden
              className="font-mono text-[10px] text-on-surface-variant/45"
            >
              &mdash;
            </span>
            <span className="text-[11.5px] text-on-surface-variant/75">
              {j1b.correlated_views_disclosure}.
            </span>
          </li>
        </ul>
        <Provenance>
          GET /evidence/mission-j &middot;{" "}
          {provenance.sources.j1b.artifact} &middot;{" "}
          {provenance.sources.j2.artifact} &middot;{" "}
          {provenance.sources.j3.artifact}
        </Provenance>
      </div>
    </div>
  );
}
