/**
 * Mission I evidence card — the ordinary-period comparison ledger on the
 * Evidence Overview page.
 *
 * First in-product consumer of the published Mission I record
 * (`GET /evidence/mission-i`, contract mission-i-evidence-v1, restored by
 * N1).  Every research value rendered here comes from the endpoint payload —
 * the backend parses the seven tracked Mission I publications at request
 * time — so this card carries no hand-copied research figure, re-runs no
 * statistic, and never pools the FOMC and OPEC ledgers.
 *
 * Editorial research-record treatment in the maintained tokens (the Mission
 * J card's visual language): hairline ledger grids for the dense numeric
 * surfaces, mono tabular numerals, interpretive italic notes, an em-dash
 * negation list for the permanent non-claims, and tiny mono provenance
 * footers.  No per-cell win/lose coloring — above- and below-midpoint
 * readings render at identical weight, structural unavailability stays a
 * first-class row, and no aggregate score, badge, or verdict is invented.
 *
 * Server ordering is preserved everywhere (frozen cell order 1..20);
 * loading, unavailable, and malformed states invent no value.
 */
import type {
  MissionIEvidenceSummary,
  MissionIFamilyLane,
  MissionIHorizon,
  MissionIPrimaryCell,
} from "@/lib/api";

export interface MissionIEvidenceCardProps {
  /** Endpoint payload; `null` / `undefined` renders the loading state. */
  data?: MissionIEvidenceSummary | null;
  /** Explicit degraded state when the contract could not be loaded. */
  unavailable?: boolean;
}

/** Contract direction vocabulary, humanized for display only. */
function directionLabel(direction: string): string {
  return direction.replace(/_/g, " ");
}

/** Contract F6 position vocabulary — "inside" / "outside" the central 50%
 *  of the calibration distribution (the frozen F6 definition). */
function f6Label(position: string): string {
  return `${position} central 50%`;
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

const CELL_TH =
  "px-2 py-1 text-left font-mono text-[9.5px] font-medium uppercase tracking-[0.08em] text-on-surface-variant/55";
const CELL_TD = "px-2 py-1 font-mono text-[11px] tabular-nums";

/** One family × horizon group of the frozen 20-cell surface. */
function HorizonCellRows({ cells }: { cells: MissionIPrimaryCell[] }) {
  return (
    <>
      {cells.map((c) => (
        <tr key={c.cell} className="border-t border-border/30">
          <td className={`${CELL_TD} text-on-surface-variant/60`}>{c.cell}</td>
          <td className={`${CELL_TD} text-on-surface`}>{c.metric}</td>
          <td className={CELL_TD}>{c.event_n_available}</td>
          <td className={CELL_TD}>{c.reference_n_available}</td>
          <td className={`${CELL_TD} text-on-surface`}>{c.memp}</td>
          <td className={`${CELL_TD} text-on-surface-variant/70`}>
            {c.signed_percentile_median}
          </td>
          <td className={CELL_TD}>{c.calibration_percentile}</td>
          <td className={`${CELL_TD} text-on-surface-variant/85`}>
            {directionLabel(c.state.memp_direction)} ·{" "}
            {f6Label(c.state.f6_position)}
          </td>
        </tr>
      ))}
    </>
  );
}

/** The per-family reference-denominator rows (eligible ordinary sessions
 *  and non-overlapping blocks per horizon, structural gaps included). */
function ReferenceRows({ lane }: { lane: MissionIFamilyLane }) {
  return (
    <>
      {lane.horizons.map((h) => (
        <tr key={`${lane.family}-${h.horizon}`} className="border-t border-border/30">
          <td className={`${CELL_TD} text-on-surface`}>{lane.family}</td>
          <td className={CELL_TD}>{h.horizon}</td>
          <td className={CELL_TD}>{lane.study_event_n_available}</td>
          <td className={`${CELL_TD} text-on-surface`}>{h.reference_n_available}</td>
          <td className={CELL_TD}>{h.non_overlapping_reference_n}</td>
          <td className={`${CELL_TD} ${h.status === "feasible" ? "text-on-surface-variant/70" : "text-on-surface"}`}>
            {h.status.replace(/_/g, " ")}
          </td>
        </tr>
      ))}
    </>
  );
}

function isContractShaped(data: MissionIEvidenceSummary): boolean {
  return Boolean(
    data &&
      Array.isArray(data.primary_cells) &&
      Array.isArray(data.universe?.families) &&
      data.universe.families.length === 2 &&
      Array.isArray(data.family_horizon_readout) &&
      Array.isArray(data.non_claims) &&
      data.falsifiers?.definitions &&
      data.falsifiers?.f3_overlap_decimation &&
      data.fragility?.knife_edge &&
      data.whole_mission_conclusion &&
      data.constitution &&
      data.provenance?.sources,
  );
}

const HORIZON_ORDER: MissionIHorizon[] = ["1d", "5d", "20d"];

export function MissionIEvidenceCard({
  data,
  unavailable = false,
}: MissionIEvidenceCardProps) {
  if (unavailable) {
    return (
      <div className="flex flex-col gap-1 rounded-md border border-border/50 p-3 text-[12.5px] leading-relaxed text-on-surface-variant/85">
        <Kicker>record unavailable</Kicker>
        <p>
          Mission I record unavailable: the <code>/evidence/mission-i</code>{" "}
          contract could not be loaded (tracked-publication drift or
          unreachable source). The separate lane is reported unavailable, not
          omitted, and no figures are shown in its place.
        </p>
      </div>
    );
  }
  if (!data) {
    return (
      <p className="text-[12.5px] leading-relaxed text-on-surface-variant/70">
        Preparing tracked Mission I record&hellip;
      </p>
    );
  }
  const fomc = data.universe?.families?.[0];
  const opec = data.universe?.families?.[1];
  if (!isContractShaped(data) || fomc === undefined || opec === undefined) {
    return (
      <div className="flex flex-col gap-1 rounded-md border border-border/50 p-3 text-[12.5px] leading-relaxed text-on-surface-variant/85">
        <Kicker>record unavailable</Kicker>
        <p>
          Mission I record unavailable: the <code>/evidence/mission-i</code>{" "}
          payload did not match the expected contract. The separate lane is
          reported unavailable, not omitted, and no figures are shown in its
          place.
        </p>
      </div>
    );
  }

  const {
    provenance,
    constitution,
    universe,
    primary_cells: cells,
    calibration,
    falsifiers,
    family_horizon_readout: readouts,
    fragility,
    whole_mission_conclusion: conclusion,
    unresolved_or_limits: limits,
    non_claims: nonClaims,
  } = data;

  const fomc20d = fomc.horizons.find((h) => h.horizon === "20d");
  const falsifierKeys = Object.keys(falsifiers.definitions) as Array<
    keyof typeof falsifiers.definitions
  >;
  const f3 = falsifiers.f3_overlap_decimation;
  const f6 = falsifiers.f6_calibration_position;
  const knife = fragility.knife_edge;
  const headline = (family: string, horizon: string) =>
    readouts.find((r) => r.family === family && r.horizon === horizon)
      ?.headline;

  const familyGroups = universe.families.map((lane) => ({
    lane,
    horizons: HORIZON_ORDER.map((horizon) => ({
      horizon,
      status: lane.horizons.find((h) => h.horizon === horizon),
      cells: cells.filter(
        (c) => c.family === lane.family && c.horizon === horizon,
      ),
    })).filter((g) => g.status !== undefined),
  }));

  return (
    <div className="flex flex-col gap-5 text-[12.5px] leading-relaxed text-on-surface/85">
      {/* A — provenance ribbon: tracked contract · published record */}
      <div className="flex flex-col gap-1 border-b border-border/30 pb-3">
        <Kicker>
          frozen protocol · published record · tracked contract{" "}
          {data.contract_version}
        </Kicker>
        <p className="text-[11.5px] text-on-surface-variant/80">
          {provenance.no_recompute_statement}
        </p>
        <p className="text-[11.5px] text-on-surface-variant/80">
          Evidence class: descriptive · comparative · frozen before any
          outcome comparison ({constitution.protocol_version}). Publication
          chain: {provenance.publication_chain}.
        </p>
      </div>

      {/* B — the frozen research question, before any result */}
      <div className="flex flex-col gap-2">
        <Kicker>Frozen research question · {constitution.protocol_version}</Kicker>
        <p className="border-l-2 border-primary/40 pl-3 text-[13px] leading-relaxed text-on-surface">
          {constitution.frozen_question}
        </p>
        <p className="text-[11.5px] text-on-surface-variant/80">
          Estimand: {constitution.estimand.name} — {plain(
            constitution.estimand.definition.replace(/^- /, ""),
          )}{" "}
          Ordinary reference midpoint:{" "}
          {constitution.estimand.ordinary_reference_midpoint}.
        </p>
        <Note>{constitution.family_pooling_prohibition}.</Note>
        <Note>{calibration.interpretation_ceiling}</Note>
      </div>

      {/* C — denominator strip: event Ns, cells, falsifiers, reference Ns */}
      <div className="flex flex-col gap-2 border-t border-border/30 pt-3">
        <Kicker>Denominators · separate ledgers, never pooled</Kicker>
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md bg-white/[0.06] sm:grid-cols-4">
          {[
            ["FOMC events", fomc.study_event_n_available],
            ["OPEC events", opec.study_event_n_available],
            ["Primary cells", constitution.primary_cell_count],
            ["Falsifier families", falsifierKeys.length],
          ].map(([label, value]) => (
            <div
              key={label}
              className="flex flex-col gap-0.5 bg-surface-container-low p-3"
            >
              <span className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-on-surface-variant/55">
                {label}
              </span>
              <span className="font-mono text-[15px] tabular-nums text-on-surface">
                {value}
              </span>
            </div>
          ))}
        </div>
        <p className="font-mono text-[10.5px] text-on-surface-variant/70">
          FOMC {fomc.primary} vs {fomc.market_benchmark} /{" "}
          {fomc.sector_benchmark} · OPEC {opec.primary} vs{" "}
          {opec.market_benchmark} / {opec.sector_benchmark} · era sessions{" "}
          {fomc.era_sessions}
        </p>
        <div className="overflow-x-auto rounded-md border border-border/40">
          <table className="w-full min-w-[560px] border-collapse">
            <caption className="sr-only">
              Ordinary-reference denominators by family and horizon
            </caption>
            <thead>
              <tr>
                {["family", "horizon", "event N", "eligible ordinary reference N", "non-overlapping blocks", "status"].map(
                  (h) => (
                    <th key={h} scope="col" className={CELL_TH}>
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              <ReferenceRows lane={fomc} />
              <ReferenceRows lane={opec} />
            </tbody>
          </table>
        </div>
        <Note>Non-overlapping blocks: {plain(universe.blocks_note)}</Note>
        {fomc20d?.limitation && (
          <p className="border-l-2 border-on-surface-variant/50 bg-surface-container-low p-3 text-[11.5px] text-on-surface-variant/85">
            FOMC 20d — {fomc20d.limitation}
          </p>
        )}
      </div>

      {/* D — family readouts: two separate sections, frozen headlines */}
      {universe.families.map((lane) => (
        <div
          key={lane.family}
          className="flex flex-col gap-2 border-t border-border/30 pt-3"
        >
          <Kicker>
            {lane.family} readout · {lane.study_event_n_available} event
            windows · separate ledger
          </Kicker>
          {HORIZON_ORDER.map((horizon) => {
            const text = headline(lane.family, horizon);
            if (text !== undefined) {
              return (
                <div key={horizon} className="flex flex-col gap-0.5">
                  <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-on-surface-variant/55">
                    {horizon}
                  </span>
                  <p className="text-[12px] leading-relaxed text-on-surface/90">
                    {text}
                  </p>
                </div>
              );
            }
            const status = lane.horizons.find((h) => h.horizon === horizon);
            if (!status || status.status === "feasible") return null;
            return (
              <div key={horizon} className="flex flex-col gap-0.5">
                <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-on-surface-variant/55">
                  {horizon} · {status.status.replace(/_/g, " ")}
                </span>
                <p className="text-[12px] leading-relaxed text-on-surface-variant/80">
                  No primary cell exists at this horizon. {status.limitation}
                </p>
              </div>
            );
          })}
        </div>
      ))}

      {/* E — the twenty-cell surface in frozen order */}
      <div className="flex flex-col gap-2 border-t border-border/30 pt-3">
        <Kicker>Twenty primary cells · frozen order · family → horizon → metric</Kicker>
        {familyGroups.map(({ lane, horizons }) => (
          <div key={lane.family} className="flex flex-col gap-1.5">
            {horizons.map(({ horizon, status, cells: horizonCells }) =>
              horizonCells[0] !== undefined ? (
                <div key={horizon} className="flex flex-col gap-1">
                  <p className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-on-surface-variant/70">
                    {lane.family} {horizon} · event N{" "}
                    {lane.study_event_n_available} · reference N{" "}
                    {horizonCells[0].reference_n_available}
                  </p>
                  <div className="overflow-x-auto rounded-md border border-border/40">
                    <table className="w-full min-w-[720px] border-collapse">
                      <caption className="sr-only">
                        {lane.family} {horizon} primary cells in frozen order
                      </caption>
                      <thead>
                        <tr>
                          {["#", "metric", "event N", "ref N", "MEMP", "signed pct median", "calib pct", "frozen reading"].map(
                            (h) => (
                              <th key={h} scope="col" className={CELL_TH}>
                                {h}
                              </th>
                            ),
                          )}
                        </tr>
                      </thead>
                      <tbody>
                        <HorizonCellRows cells={horizonCells} />
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <p
                  key={horizon}
                  className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-on-surface-variant/70"
                >
                  {lane.family} {horizon} ·{" "}
                  {status?.status.replace(/_/g, " ")} · no primary cells
                </p>
              ),
            )}
          </div>
        ))}
        <Note>
          {constitution.signed_percentile_disclosure.status} — the signed
          percentile medians:{" "}
          {constitution.signed_percentile_disclosure.disclaimers
            .map(plain)
            .join(" ")}
        </Note>
      </div>

      {/* F — falsifier battery: six families, reported separately */}
      <div className="flex flex-col gap-2 border-t border-border/30 pt-3">
        <Kicker>Falsifier battery · six families, reported separately</Kicker>
        <Note>{plain(falsifiers.battery_disclosure)}.</Note>

        {/* F1 */}
        <div className="flex flex-col gap-1 bg-surface-container-low p-3">
          <p className="font-mono text-[11px] text-on-surface">F1 · leave-one-year-out</p>
          <p className="text-[11px] text-on-surface-variant/80">
            {plain(falsifiers.definitions.f1)}
          </p>
          <p className="font-mono text-[11px] tabular-nums text-on-surface">
            {falsifiers.f1_loyo.flips_total} / {falsifiers.f1_loyo.runs_total}{" "}
            leave-out runs flip sign(MEMP − 0.5)
          </p>
          <p className="font-mono text-[10.5px] tabular-nums text-on-surface-variant/85">
            affected cells:{" "}
            {falsifiers.f1_loyo.affected_cells
              .map((a) => `${a.cell_key} ${a.flips} / ${a.of}`)
              .join(" · ")}
          </p>
        </div>

        {/* F2 */}
        <div className="flex flex-col gap-1 bg-surface-container-low p-3">
          <p className="font-mono text-[11px] text-on-surface">F2 · leave-one-event-out</p>
          <p className="text-[11px] text-on-surface-variant/80">
            {plain(falsifiers.definitions.f2)}
          </p>
          <p className="font-mono text-[11px] tabular-nums text-on-surface">
            {falsifiers.f2_loeo.flips_total} / {falsifiers.f2_loeo.runs_total}{" "}
            leave-out runs flip sign(MEMP − 0.5)
          </p>
          <p className="font-mono text-[10.5px] tabular-nums text-on-surface-variant/85">
            affected cells:{" "}
            {falsifiers.f2_loeo.affected_cells
              .map((a) => `${a.cell_key} ${a.flips} / ${a.of}`)
              .join(" · ")}
          </p>
          <Note>{plain(falsifiers.f2_loeo.knife_edge_explanation)}</Note>
        </div>

        {/* F3 */}
        <div className="flex flex-col gap-1 bg-surface-container-low p-3">
          <p className="font-mono text-[11px] text-on-surface">F3 · overlap decimation</p>
          <p className="text-[11px] text-on-surface-variant/80">
            {plain(falsifiers.definitions.f3)}
          </p>
          <p className="font-mono text-[11px] tabular-nums text-on-surface">
            {f3.sign_flips} / {f3.of_cells} primary-cell direction changes
          </p>
          <p className="text-[11px] text-on-surface-variant/85">{f3.reading}</p>
          <Note>{f3.limitation}</Note>
        </div>

        {/* F4 */}
        <div className="flex flex-col gap-1 bg-surface-container-low p-3">
          <p className="font-mono text-[11px] text-on-surface">F4 · cross-metric consistency</p>
          <p className="text-[11px] text-on-surface-variant/80">
            {plain(falsifiers.definitions.f4)}
          </p>
          <div className="overflow-x-auto rounded-md border border-border/40">
            <table className="w-full min-w-[420px] border-collapse">
              <caption className="sr-only">
                F4 cross-metric sign counts per family and horizon
              </caption>
              <thead>
                <tr>
                  {["family × horizon", "above midpoint", "at midpoint", "below midpoint"].map((h) => (
                    <th key={h} scope="col" className={CELL_TH}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {falsifiers.f4_cross_metric.map((row) => (
                  <tr
                    key={`${row.family}-${row.horizon}`}
                    className="border-t border-border/30"
                  >
                    <td className={`${CELL_TD} text-on-surface`}>
                      {row.family} {row.horizon}
                    </td>
                    <td className={CELL_TD}>{row.positive}</td>
                    <td className={CELL_TD}>{row.zero}</td>
                    <td className={CELL_TD}>{row.negative}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* F5 */}
        <div className="flex flex-col gap-1 bg-surface-container-low p-3">
          <p className="font-mono text-[11px] text-on-surface">F5 · cross-horizon consistency</p>
          <p className="text-[11px] text-on-surface-variant/80">
            {plain(falsifiers.definitions.f5)}
          </p>
          <div className="overflow-x-auto rounded-md border border-border/40">
            <table className="w-full min-w-[480px] border-collapse">
              <caption className="sr-only">
                F5 cross-horizon sign agreement per family and metric
              </caption>
              <thead>
                <tr>
                  {["family", "metric", "1d", "5d", "20d", "feasible horizons agree"].map((h) => (
                    <th key={h} scope="col" className={CELL_TH}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {falsifiers.f5_cross_horizon.map((row) => (
                  <tr
                    key={`${row.family}-${row.metric}`}
                    className="border-t border-border/30"
                  >
                    <td className={`${CELL_TD} text-on-surface`}>{row.family}</td>
                    <td className={CELL_TD}>{row.metric}</td>
                    {HORIZON_ORDER.map((h) => (
                      <td key={h} className={CELL_TD}>
                        {row.signs[h] === null
                          ? "n/a"
                          : row.signs[h]! > 0
                            ? "above"
                            : row.signs[h]! < 0
                              ? "below"
                              : "at"}
                      </td>
                    ))}
                    <td className={`${CELL_TD} text-on-surface-variant/85`}>
                      {row.agree ? "agree" : "disagree"}
                      {row.caveat !== null ? " (see caveat)" : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {falsifiers.f5_cross_horizon
            .filter((row) => row.caveat !== null)
            .map((row) => (
              <Note key={`${row.family}-${row.metric}-caveat`}>
                {row.family} {row.metric} caveat (verbatim):{" "}
                {plain(row.caveat as string)}
              </Note>
            ))}
        </div>

        {/* F6 */}
        <div className="flex flex-col gap-1 bg-surface-container-low p-3">
          <p className="font-mono text-[11px] text-on-surface">F6 · calibration position</p>
          <p className="text-[11px] text-on-surface-variant/80">
            {plain(falsifiers.definitions.f6)}
          </p>
          <p className="font-mono text-[11px] tabular-nums text-on-surface">
            {f6.inside} inside · {f6.outside} outside the central 50% (
            {f6.outside_upper} upper · {f6.outside_lower} lower)
          </p>
          <Note>{plain(f6.limitation.replace(/\s*## \d+\.\s*$/, ""))}</Note>
        </div>
      </div>

      {/* G — fragility: the knife-edge cell at full weight */}
      <div className="flex flex-col gap-2 border-t border-border/30 pt-3">
        <Kicker>Fragility · concentrated in one knife-edge cell</Kicker>
        <div className="flex flex-col gap-1 border-l-2 border-on-surface-variant/50 bg-surface-container-low p-3">
          <p className="font-mono text-[11px] text-on-surface">
            {knife.cell_key} · MEMP {knife.memp} · calibration{" "}
            {knife.calibration_percentile}
          </p>
          <p className="font-mono text-[10.5px] tabular-nums text-on-surface-variant/85">
            LOYO {knife.f1_loyo.flips} / {knife.f1_loyo.runs} · LOEO{" "}
            {knife.f2_loeo.flips} / {knife.f2_loeo.runs}
          </p>
          <p className="text-[11.5px] text-on-surface-variant/85">
            {plain(knife.explanation)}
          </p>
        </div>
        <p className="font-mono text-[10.5px] tabular-nums text-on-surface-variant/70">
          all LOYO-affected cells:{" "}
          {fragility.loyo_affected_cells
            .map((a) => `${a.cell_key} ${a.flips} / ${a.of}`)
            .join(" · ")}
        </p>
      </div>

      {/* H — era-matched placement calibration */}
      <div className="flex flex-col gap-2 border-t border-border/30 pt-3">
        <Kicker>Era-matched placement calibration</Kicker>
        <p className="font-mono text-[11px] tabular-nums text-on-surface-variant/85">
          {calibration.placements_per_group.toLocaleString("en-US")} placements
          per family × horizon group · fixed seed {calibration.seed} ·{" "}
          {calibration.groups
            .map(
              (g) =>
                `${g.family} ${g.horizon} ${g.completed_placements}/${g.expected_placements}`,
            )
            .join(" · ")}
        </p>
        <p className="text-[11px] text-on-surface-variant/80">
          {calibration.method}
        </p>
        <Note>{calibration.interpretation_ceiling}</Note>
      </div>

      {/* I — whole-mission conclusion + formal-test clarifier, adjacent */}
      <div className="flex flex-col gap-2 border-t border-border/30 pt-3">
        <Kicker>Whole-mission conclusion · descriptive only</Kicker>
        <p className="border-l-2 border-primary/40 pl-3 text-[13px] leading-relaxed text-on-surface">
          {conclusion.statement}
        </p>
        <Note>{conclusion.clarifier}</Note>
      </div>

      {/* J — limitations and unresolved states, visible without disclosure */}
      <div className="flex flex-col gap-1.5 border-t border-border/30 pt-3">
        <Kicker>Limitations and unresolved</Kicker>
        <ul className="flex flex-col gap-1">
          {limits.map((line) => (
            <li
              key={line}
              className="flex items-start gap-1.5 text-[11.5px] leading-relaxed text-on-surface-variant/75"
            >
              <span
                aria-hidden
                className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-on-surface-variant/40"
              />
              {plain(line)}
            </li>
          ))}
        </ul>
      </div>

      {/* K — permanent non-claims: em-dash negation ledger + provenance */}
      <div className="flex flex-col gap-1.5 border-t border-border/30 pt-3">
        <Kicker>Permanent non-claims · what this record does not establish</Kicker>
        <ul className="flex flex-col gap-0.5">
          {nonClaims.map((line) => (
            <li key={line} className="flex items-baseline gap-2">
              <span
                aria-hidden
                className="font-mono text-[10px] text-on-surface-variant/45"
              >
                &mdash;
              </span>
              <span className="text-[11.5px] text-on-surface-variant/75">
                {plain(line)}
              </span>
            </li>
          ))}
        </ul>
        <Provenance>
          GET /evidence/mission-i &middot; {data.contract_version} &middot;{" "}
          {Object.values(provenance.sources)
            .map((s) => s.artifact)
            .join(" · ")}
        </Provenance>
        <Provenance>
          reproduction (recorded in {provenance.reproduction.source}):{" "}
          {provenance.reproduction.commands.join(" · ")} &middot;{" "}
          {provenance.reproduction.reproducibility_limits} computation dates
          and execution commits: not recorded in any Mission I publication.
        </Provenance>
      </div>
    </div>
  );
}
