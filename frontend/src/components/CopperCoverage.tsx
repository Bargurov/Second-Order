import { useMemo, useRef, useState } from "react";
import { previewScenario, saveScenario, type Action, type AssessResult, type Preview, type Saved } from "../copperActions";
import { inputKey, Latest, latest } from "../copperRequests";
import {
  COUNTRY_IDS, fetchCopperTools, type Assumptions, type Baseline, type CopperToolsView, type Perturbation, type RecordItem,
  type ScenarioId, type Year,
} from "../copperTools";
import { shortHash } from "../format";
import { ComputedValue, FigureValue, Kind, Plain, PublishedValue, SectionHead } from "./CopperBits";

type Mode = "none" | "scenario" | "technology_case" | "value";
interface ComponentInput { mode: Mode; scenario: ScenarioId; kt: string }
interface MineInput { mode: "none" | "total" | "countries"; kt: string; reference: string | null;
  factors: Record<string, string> }
const KIND_LABELS: Record<string, string> = {
  published_scenario_value: "Published scenario values", published_technology_case: "Published technology case",
  reference_magnitude: "Reference magnitudes (company disclosures)", user_declared: "Your entered change",
  published_totals: "Published totals, all components together",
};
const CONTROL_LABELS: Record<string, string> = { ev: "Copper used in electric vehicles",
  networks: "Copper used in electricity networks", mine: "Counted mine supply", joint: "Joint published scenario" };

/** Sections 4 to 8 of the copper tools page: the published baseline, the three controls, the results, the
 * perturbations and saving a scenario. The page computes nothing: every number is served and passed the reader. */
export function CopperCoverage({ view, onSaved }: { view: CopperToolsView; onSaved: (records: RecordItem[]) => void }) {
  const c = view.coverage;
  const [scenario, setScenario] = useState<ScenarioId>(c.scenarios[0].id);
  const [year, setYear] = useState<Year>(c.years[0]);
  const [ev, setEv] = useState<ComponentInput>({ mode: "none", scenario: c.scenarios[0].id, kt: "" });
  const [networks, setNetworks] = useState<ComponentInput>({ mode: "none", scenario: c.scenarios[0].id, kt: "" });
  const [mine, setMine] = useState<MineInput>({ mode: "none", kt: "", reference: null, factors: {} });
  // A preview is kept with the inputs it was computed for; a save is reported with the scenario it saved.
  const [preview, setPreview] = useState<{ key: string; reply: Action<Preview> } | null>(null);
  const [label, setLabel] = useState("");
  const [saved, setSaved] = useState<{ label: string; scenario: ScenarioId; year: Year;
    reply: Action<Saved> } | null>(null);
  const [computing, setComputing] = useState(false);
  const [saving, setSaving] = useState(false);
  const gate = useRef(new Latest());
  const base = c.baselines.find((item) => item.scenario === scenario && item.year === year) as Baseline;
  /** An input changed: a preview in flight or on screen no longer describes the inputs, so neither is used. */
  const stale = () => { gate.current.invalidate(); setPreview(null); setComputing(false); };

  const assumptions = useMemo((): Assumptions => ({
    ev: ev.mode === "none" ? null : ev.mode === "value" ? { source: "value", kt: ev.kt.trim() }
      : { source: "scenario", scenario: ev.scenario },
    networks: networks.mode === "none" ? null : networks.mode === "value" ? { source: "value", kt: networks.kt.trim() }
      : { source: networks.mode as "scenario" | "technology_case", scenario: networks.scenario },
    mine: mine.mode === "none" ? null : mine.mode === "total"
      ? { source: "total", kt: mine.kt.trim(), reference: mine.reference }
      : { source: "countries", factors: Object.fromEntries(Object.entries(mine.factors)
        .filter(([, value]) => value.trim() !== "").map(([key, value]) => [key, value.trim()])) },
  }), [ev, networks, mine]);
  const key = inputKey({ scenario, year, assumptions });
  const currentKey = useRef(key);
  currentKey.current = key;

  async function compute() {
    setComputing(true);
    const outcome = await latest(gate.current, key, () => currentKey.current,
                                 () => previewScenario(view, { scenario, year, assumptions }));
    if (!outcome.used) return;  // Superseded or sent for other inputs: never shown, never saved.
    setPreview({ key, reply: outcome.value });
    setComputing(false);
  }
  // Only a preview of the inputs now on the page is shown or saved.
  const current = preview !== null && preview.key === key ? preview.reply : null;
  const result: AssessResult | null = current?.state === "ready" ? current.data.result : null;
  async function save() {
    if (result === null) return;
    const shown = result;  // Saving sends exactly the previewed inputs, and the reply must be that scenario.
    const savedLabel = label.trim();
    setSaving(true);
    const reply = await saveScenario(view, shown, savedLabel);
    setSaved({ label: savedLabel, scenario: shown.scenario, year: shown.year, reply });
    if (reply.state === "ready") {
      const fresh = await fetchCopperTools(new AbortController().signal);
      if (fresh.state === "ready") onSaved(fresh.data.scenarios.records);
    }
    setSaving(false);
  }
  const scenarioLabel = Object.fromEntries(c.scenarios.map((item) => [item.id, item.label]));

  return (
    <>
      <section id="baseline" className="library-section-block ct-section" aria-labelledby="baseline-title">
        <SectionHead id="baseline" kicker="04 · Published baseline" title="The IEA's published figures for one year">
          <Plain>Choose a year and one of the IEA's published scenarios. A scenario is a consistent set of assumptions,
            not a probability.</Plain>
        </SectionHead>
        <div className="ct-selectors">
          <fieldset><legend>Year</legend>
            {c.years.map((item) => (
              <label key={item}><input type="radio" name="ct-year" value={item} checked={year === item}
                onChange={() => { setYear(item); stale(); }} />{item}</label>))}
          </fieldset>
          <fieldset><legend>Published scenario</legend>
            {c.scenarios.map((item) => (
              <label key={item.id}><input type="radio" name="ct-scenario" value={item.id} checked={scenario === item.id}
                onChange={() => { setScenario(item.id); stale(); }} />{item.label}</label>))}
          </fieldset>
        </div>
        <Demand view={view} base={base} />
        <Mine view={view} base={base} />
        <Refining view={view} base={base} />
      </section>

      <section id="controls" className="library-section-block ct-section" aria-labelledby="controls-title">
        <SectionHead id="controls" kicker="05 · Controls" title="Three controls, all in copper tonnes">
          <Plain>Mixing parts of two scenarios makes a hybrid: the IEA's scenarios move together, so a mixed set is not
            an IEA scenario. Recycling is not an input in this version.</Plain>
        </SectionHead>
        <ComponentControl view={view} id="ev" value={ev} year={year}
          onChange={(next) => { setEv(next); stale(); }} />
        <ComponentControl view={view} id="networks" value={networks} year={year}
          onChange={(next) => { setNetworks(next); stale(); }} />
        <MineControl view={view} value={mine} base={base} onChange={(next) => { setMine(next); stale(); }} />
        <p className="ct-actions">
          <button type="button" className="button" onClick={compute} disabled={computing}>Compute with these
            inputs</button>
          <span className="ct-note">Computing writes nothing.</span>
        </p>
        {current && current.state !== "ready" && <p role="alert" className="ct-error">{current.message}</p>}
      </section>

      <Results view={view} base={base} result={result} />
      <Perturbations view={view} rows={result?.perturbations ?? base.perturbations} assumed={result !== null} />

      <section id="save" className="library-section-block ct-section" aria-labelledby="save-title">
        <SectionHead id="save" kicker="08 · Save this scenario" title="A write-once record">
          <Plain>A record keeps the inputs, every figure used with its source's SHA-256, and the result. It is checked
            again on every read. It holds a short label and no commentary.</Plain>
        </SectionHead>
        <p className="ct-actions">
          <label className="ct-label">Label <input type="text" maxLength={80} value={label}
            onChange={(event) => setLabel(event.target.value)} /></label>
          <button type="button" className="button" onClick={save}
                  disabled={saving || result === null || label.trim() === ""}>Save this scenario</button>
        </p>
        {result === null && <p className="ct-note">Compute the scenario with the inputs above first; the record saves
          exactly what the preview shows, and a changed input needs a new computation.</p>}
        {saved?.reply.state === "ready" && (
          <p role="status" className="ct-saved" data-status={saved.reply.data.status}
             data-saved-scenario={saved.scenario} data-saved-year={saved.year}>
            {saved.reply.data.status === "created" ? "Saved" : "Already saved; nothing was written"}: record{" "}
            <code>{shortHash(saved.reply.data.id, 12)}</code> for {scenarioLabel[saved.scenario]} {saved.year},
            labelled “{saved.label}”; {view.scenarios.labels[saved.reply.data.state] ?? saved.reply.data.state}.
          </p>)}
        {saved && saved.reply.state !== "ready" && (
          <p role="alert" className="ct-error" data-saved-scenario={saved.scenario} data-saved-year={saved.year}>
            Saving {scenarioLabel[saved.scenario]} {saved.year} (“{saved.label}”): {saved.reply.message}</p>)}
      </section>
    </>
  );
}

function Demand({ view, base }: { view: CopperToolsView; base: Baseline }) {
  const labels = Object.fromEntries([...view.coverage.components, ...view.coverage.totals].map((x) => [x.id, x.label]));
  return (
    <div className="ct-block">
      <h3>World copper demand, {base.year}</h3>
      <div className="ct-table-wrap"><table className="ct-table" data-table="demand">
        <thead><tr><th scope="col">Use</th><th scope="col">kt</th></tr></thead>
        <tbody>
          {base.demand.map((row) => (
            <tr key={row.line} data-line={row.line} className={["energy", "total"].includes(row.line) ? "ct-total" : ""}>
              <th scope="row">{labels[row.line]}</th><td><PublishedValue view={view} entry={row} /></td></tr>))}
          <tr data-line="epsilon"><th scope="row">Energy total minus its printed parts (ε)</th>
            <td><ComputedValue item={base.epsilon} /></td></tr>
          <tr data-line="delta"><th scope="row">Total minus energy and other uses (δ)</th>
            <td><ComputedValue item={base.delta} /></td></tr>
        </tbody>
      </table></div>
      <Plain>The IEA's parts do not add exactly to its totals; changes are applied to the printed total, and the
        difference is shown, never spread over the parts.</Plain>
    </div>
  );
}

function Mine({ view, base }: { view: CopperToolsView; base: Baseline }) {
  const labels = Object.fromEntries(view.coverage.countries.map((x) => [x.id, x.label]));
  return (
    <div className="ct-block">
      <h3>Counted mine supply, {base.year} (IEA “Copper - Mining”, base case)</h3>
      <div className="ct-table-wrap"><table className="ct-table" data-table="mine">
        <thead><tr><th scope="col">Country</th><th scope="col">kt</th></tr></thead>
        <tbody>{base.mine.map((row) => (
          <tr key={row.country} className={row.country === "total" ? "ct-total" : ""}>
            <th scope="row">{labels[row.country] ?? "Total"}</th><td><PublishedValue view={view} entry={row} /></td>
          </tr>))}</tbody>
      </table></div>
      <Plain>The IEA builds these supply figures from operating and announced projects, weighted by how likely each is to
        come online; projects not yet announced are not in them.</Plain>
    </div>
  );
}

function Refining({ view, base }: { view: CopperToolsView; base: Baseline }) {
  const r = view.coverage.refining;
  return (
    <aside className="ct-refining" aria-labelledby="refining-title" data-source-name={r.source_name}>
      <h3 id="refining-title">IEA base-case refining supply: “{r.source_name}”</h3>
      <p>{base.year}: <PublishedValue view={view} entry={base.refining} /> kt, from the sheet “{r.sheet_title}”.
        Shown apart: it is never added to mining supply or set against demand.</p>
      <p className="policy-label">What the sheet's notes say</p>
      <ul>{r.notes.map((id) => (
        <li key={id} data-passage={id}>{view.passages[id].text === null ? "Withheld: not verified"
          : <q>{view.passages[id].text}</q>}</li>))}</ul>
      <p className="policy-label">Not stated, so unknown</p>
      <ul data-unknowns="">{r.unknowns.map((text) => <li key={text}>{text}</li>)}</ul>
      <p className="policy-label">Reading, labelled as such</p>
      <p>{r.interpretation}</p>
      <Plain>The refining figures do not say whether they count refining of scrap, or whether enough concentrate and scrap
        would exist to feed them, so they are not compared with demand.</Plain>
    </aside>
  );
}

function ComponentControl({ view, id, value, year, onChange }: { view: CopperToolsView; id: "ev" | "networks";
  value: ComponentInput; year: Year; onChange: (next: ComponentInput) => void }) {
  const control = view.coverage.controls.find((item) => item.id === id)!;
  const dc = view.coverage.dc_scenarios;
  const modes: [Mode, string][] = [["none", "No adjustment: the selected scenario's value"],
    ["scenario", "Another published scenario's value"], ...(id === "networks"
      ? [["technology_case", `The published “${view.coverage.dc_label}” case`] as [Mode, string]] : []),
    ["value", "A value you enter, in kt"]];
  const scenarios = value.mode === "technology_case"
    ? view.coverage.scenarios.filter((item) => dc.includes(item.id)) : view.coverage.scenarios;
  return (
    <fieldset className="ct-control" data-control={id}>
      <legend>{control.label}</legend>
      <p className="ct-note">{control.meaning} Not offered: {control.not_offered}</p>
      {modes.map(([mode, text]) => (
        <label key={mode}><input type="radio" name={`ct-${id}`} checked={value.mode === mode}
          onChange={() => onChange({ ...value, mode, scenario: mode === "technology_case" && !dc.includes(value.scenario)
            ? dc[0] as ScenarioId : value.scenario })} />{text}</label>))}
      {(value.mode === "scenario" || value.mode === "technology_case") && (
        <label className="ct-inline">Scenario <select value={value.scenario}
          onChange={(event) => onChange({ ...value, scenario: event.target.value as ScenarioId })}>
          {scenarios.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select>{" "}
          <FigureValue view={view} id={value.mode === "technology_case" ? `iea-networks-dc-${value.scenario}-${year}`
            : `iea-demand-${id}-${value.scenario}-${year}`} /></label>)}
      {value.mode === "value" && (
        <label className="ct-inline">kt <input type="text" inputMode="decimal" value={value.kt}
          onChange={(event) => onChange({ ...value, kt: event.target.value })} />
          <Kind kind="assumption" title="Assumption: entered by the user" /></label>)}
    </fieldset>
  );
}

function MineControl({ view, value, base, onChange }: { view: CopperToolsView; value: MineInput; base: Baseline;
  onChange: (next: MineInput) => void }) {
  const control = view.coverage.controls.find((item) => item.id === "mine")!;
  const references = base.perturbations.find((row) => row.kind === "reference_magnitude")?.cases ?? [];
  const labels = Object.fromEntries(view.coverage.countries.map((x) => [x.id, x.label]));
  return (
    <fieldset className="ct-control" data-control="mine">
      <legend>{control.label}</legend>
      <p className="ct-note">{control.meaning} Not offered: {control.not_offered}</p>
      {([["none", "No adjustment"], ["total", "A signed change in kt"], ["countries", "A factor for one or more countries"]
      ] as [MineInput["mode"], string][]).map(([mode, text]) => (
        <label key={mode}><input type="radio" name="ct-mine" checked={value.mode === mode}
          onChange={() => onChange({ ...value, mode })} />{text}</label>))}
      {value.mode === "total" && (
        <div className="ct-inline-block">
          <label className="ct-inline">Change, kt <input type="text" inputMode="decimal" value={value.kt}
            onChange={(event) => onChange({ ...value, kt: event.target.value, reference: null })} />
            <Kind kind="assumption" title="Assumption: entered by the user" /></label>
          <p className="ct-note">Reference magnitudes (company disclosures, not projections or defaults):</p>
          <ul className="ct-references">{references.map((item) => (
            <li key={item.reference}>{item.label}: <ComputedValue item={item.magnitude} /> kt{" "}
              {item.magnitude?.value && (
                <>
                  <button type="button" className="button button-quiet" onClick={() => onChange({ ...value,
                    kt: `-${item.magnitude!.value}`, reference: item.reference as string })}>Enter as a reduction</button>
                  <button type="button" className="button button-quiet" onClick={() => onChange({ ...value,
                    kt: item.magnitude!.value as string, reference: item.reference as string })}>Enter as an increase</button>
                </>)}</li>))}</ul>
          {value.reference && <p className="ct-note">Tagged as a reference magnitude; the exact value is entered.</p>}
        </div>)}
      {value.mode === "countries" && (
        <div className="ct-factors">{COUNTRY_IDS.map((country) => (
          <label key={country} className="ct-inline">{labels[country]} factor <input type="text" inputMode="decimal"
            value={value.factors[country] ?? ""} placeholder="no change"
            onChange={(event) => onChange({ ...value, factors: { ...value.factors, [country]: event.target.value } })} />
          </label>))}</div>)}
    </fieldset>
  );
}

function Results({ view, base, result }: { view: CopperToolsView; base: Baseline; result: AssessResult | null }) {
  const d = base.decomposition;
  const labels = Object.fromEntries([...view.coverage.components, ...view.coverage.totals].map((x) => [x.id, x.label]));
  return (
    <section id="results" className="library-section-block ct-section" aria-labelledby="results-title">
      <SectionHead id="results" kicker="06 · Results" title="Demand not covered by the counted mine pipeline">
        <Plain>R is what the counted pipeline leaves to recycling, mines not yet counted, stocks or lower demand; it is
          not a shortage.</Plain>
      </SectionHead>
      <div className="ct-table-wrap"><table className="ct-table" data-table="results">
        <thead><tr><th scope="col">{base.year}</th><th scope="col">Published baseline</th>
          <th scope="col">With your inputs</th></tr></thead>
        <tbody>
          <tr><th scope="row">Demand D (kt)</th><td><PublishedValue view={view} entry={base.coverage.demand} /></td>
            <td><ComputedValue item={result?.demand} /></td></tr>
          <tr><th scope="row">Counted mine supply M (kt)</th><td><PublishedValue view={view} entry={base.coverage.mine} /></td>
            <td><ComputedValue item={result?.mine} /></td></tr>
          <tr className="ct-total" data-row="residual"><th scope="row">R = D − M (kt)</th>
            <td><ComputedValue item={base.coverage.residual} /></td><td><ComputedValue item={result?.residual} /></td></tr>
          <tr><th scope="row">R as a share of demand (%)</th><td><ComputedValue item={base.coverage.share_pct} unit="percent" /></td>
            <td><ComputedValue item={result?.share_pct} unit="percent" /></td></tr>
          <tr><th scope="row">Change in R since 2025 (kt)</th><td><ComputedValue item={d.residual_change} signed /></td>
            <td><ComputedValue item={result?.residual_change} signed /></td></tr>
        </tbody>
      </table></div>
      <p className="ct-note">2025 is the dataset's base year (a model base year, not an outturn): R there is{" "}
        <ComputedValue item={base.base.residual} /> kt.</p>
      {result && result.flags.length > 0 && (
        <ul className="ct-flags" aria-label="Flags on these inputs">
          {result.flags.map((flag) => <li key={flag.id} data-flag={flag.id}>{flag.text}</li>)}</ul>)}
      <h3>How R changed since 2025 (published baseline)</h3>
      <div className="ct-table-wrap"><table className="ct-table" data-table="decomposition">
        <thead><tr><th scope="col">Part</th><th scope="col">Change, kt</th></tr></thead>
        <tbody>
          {d.demand_rows.map((row) => <tr key={row.line} className={["energy", "total"].includes(row.line) ? "ct-total" : ""}>
            <th scope="row">{labels[row.line]}</th><td><ComputedValue item={row.change} signed /></td></tr>)}
          <tr><th scope="row">Change in ε</th><td><ComputedValue item={d.epsilon_change} signed /></td></tr>
          <tr><th scope="row">Change in δ</th><td><ComputedValue item={d.delta_change} signed /></td></tr>
          <tr><th scope="row">Change in counted mine supply</th><td><ComputedValue item={d.mine_change} signed /></td></tr>
          <tr className="ct-total"><th scope="row">Change in R (demand change minus mine change)</th>
            <td><ComputedValue item={d.residual_change} signed /></td></tr>
        </tbody>
      </table></div>
      <h3>Not computed here</h3>
      <ul className="ct-not-computed">{view.coverage.not_computed.map((text) => <li key={text}>{text}</li>)}</ul>
    </section>
  );
}

function Perturbations({ view, rows, assumed }: { view: CopperToolsView; rows: Perturbation[]; assumed: boolean }) {
  return (
    <section id="perturbations" className="library-section-block ct-section" aria-labelledby="perturbations-title">
      <SectionHead id="perturbations" kicker="07 · Perturbations" title="How far R moves for a stated change">
        <Plain>Each row shows how far R moves for a stated change; the ranges are of different kinds and are not ranked.
          {assumed ? " Around the published baseline, with your entered mine change as its own row." : ""}</Plain>
      </SectionHead>
      <div className="ct-table-wrap"><table className="ct-table" data-table="perturbations">
        <thead><tr><th scope="col">Control</th><th scope="col">Kind of range</th><th scope="col">Case</th>
          <th scope="col">Effect on R, kt</th></tr></thead>
        <tbody>{rows.flatMap((row, index) => row.cases.map((item, n) => (
          <tr key={`${index}-${n}`} data-kind={row.kind}>
            {n === 0 && <th scope="row" rowSpan={row.cases.length}>{CONTROL_LABELS[row.control]}</th>}
            {n === 0 && <td rowSpan={row.cases.length}>{KIND_LABELS[row.kind]}</td>}
            <td>{item.label}{item.value && <> (<PublishedValue view={view} entry={item.value} />)</>}
              {item.magnitude && <> (<ComputedValue item={item.magnitude} /> kt)</>}</td>
            <td>{item.effect ? <ComputedValue item={item.effect} signed />
              : <>if counted mine supply is lower by it: <ComputedValue item={item.effect_if_lower} signed />;
                if higher: <ComputedValue item={item.effect_if_higher} signed /></>}</td>
          </tr>)))}</tbody>
      </table></div>
    </section>
  );
}
